"""Agentic extraction: a bounded ReAct loop over Pawgrab's own tools.

The model is driven one step at a time via the existing JSON-returning provider
interface (``provider.extract``), so no new provider method is required. Each step
the model picks a tool — ``fetch``, ``search``, or ``finish`` — and the loop
executes it, accumulating page content until the schema is satisfied or the budget
runs out.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import structlog

from pawgrab.config import settings
from pawgrab.engine.cleaner import extract_content
from pawgrab.engine.converter import html_to_markdown
from pawgrab.engine.fetcher import fetch_page
from pawgrab.models.agent import AgentResponse, AgentStep, Effort
from pawgrab.utils.rate_limiter import guard_url

logger = structlog.get_logger()

_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["fetch", "search", "finish"]},
        "url": {"type": ["string", "null"], "description": "URL to fetch (action=fetch)"},
        "query": {"type": ["string", "null"], "description": "Web search query (action=search)"},
        "reason": {"type": "string", "description": "One short sentence: why this step"},
        "data": {"type": ["object", "null"], "description": "Final extracted object (action=finish only)"},
    },
    "required": ["action", "reason"],
}

_EFFORT_STEPS = {
    Effort.LOW: lambda: settings.agent_steps_low,
    Effort.MEDIUM: lambda: settings.agent_steps_medium,
    Effort.HIGH: lambda: settings.agent_steps_high,
}


def _budget(effort: Effort, max_steps: int | None) -> int:
    if max_steps is not None:
        return max_steps
    return _EFFORT_STEPS[effort]()


def _domain_ok(url: str, allowed: list[str]) -> bool:
    if not allowed:
        return True
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    return any(host == d.lower().removeprefix("www.") or host.endswith(f".{d.lower().removeprefix('www.')}") for d in allowed)


async def _fetch_markdown(url: str, timeout: int, browser_pool: object | None) -> str:
    """Fetch → clean → markdown, reusing the standard scrape pipeline."""
    await guard_url(url)
    result = await fetch_page(url, timeout=timeout, browser_pool=browser_pool)
    cleaned = extract_content(result.html, url=result.url)
    return html_to_markdown(cleaned.content_html)


def _validate(data: Any, json_schema: dict | None) -> tuple[bool, str | None]:
    if not isinstance(data, dict):
        return False, "agent did not return an object"
    if not json_schema:
        return True, None
    try:
        import jsonschema

        jsonschema.validate(data, json_schema)
        return True, None
    except ModuleNotFoundError:
        # jsonschema is optional; accept the object if the library isn't present.
        return True, None
    except Exception as exc:  # jsonschema.ValidationError
        return False, f"schema validation failed: {getattr(exc, 'message', str(exc))}"


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


async def run_agent(
    *,
    prompt: str,
    urls: list[str],
    json_schema: dict | None,
    effort: Effort,
    max_steps: int | None,
    allowed_domains: list[str],
    timeout: int,
    browser_pool: object | None = None,
) -> AgentResponse:
    """Run the bounded extraction agent and return its result."""
    from pawgrab.ai.extractor import get_provider

    provider = get_provider()
    budget = _budget(effort, max_steps)
    steps: list[AgentStep] = []
    sources: list[str] = []
    visited: set[str] = set()
    total_tokens = 0

    # Seed the context: fetch given URLs, else leave empty so the model searches.
    context_parts: list[str] = []
    seed_queue = [str(u) for u in urls]

    async def _do_fetch(url: str, reason: str) -> None:
        nonlocal total_tokens
        if url in visited:
            return
        if not _domain_ok(url, allowed_domains):
            steps.append(AgentStep(action="fetch", url=url, reason="rejected: off allowed_domains"))
            return
        visited.add(url)
        try:
            md = await _fetch_markdown(url, timeout, browser_pool)
        except Exception as exc:
            steps.append(AgentStep(action="fetch", url=url, reason=f"fetch failed: {type(exc).__name__}"))
            return
        try:
            from pawgrab.engine import index as _index

            await _index.upsert(url, md)
        except Exception:
            pass
        md = md[:12_000]
        context_parts.append(f"### Source: {url}\n{md}")
        sources.append(url)
        tok = _estimate_tokens(md)
        total_tokens += tok
        steps.append(AgentStep(action="fetch", url=url, reason=reason, tokens=tok))

    # Pre-fetch any seeds (counts against the budget).
    for url in seed_queue[:budget]:
        await _do_fetch(url, "seed URL")

    for _ in range(budget):
        if total_tokens > settings.agent_token_cap:
            break
        context = "\n\n".join(context_parts)[: settings.agent_token_cap * 4] or "(no pages fetched yet)"
        step_prompt = (
            f"GOAL: {prompt}\n\n"
            f"You are a web-research agent. Decide the single next action.\n"
            f"- action='search' with a 'query' to find candidate URLs (use when you have no useful content yet).\n"
            f"- action='fetch' with a 'url' to read a page (only URLs that appear in the content above).\n"
            f"- action='finish' with 'data' once you can satisfy the goal"
            f"{' and the required schema' if json_schema else ''}.\n"
            f"Pages already read: {sources or 'none'}."
        )
        if json_schema:
            step_prompt += f"\n\nThe final 'data' must satisfy this JSON schema:\n{json_schema}"

        try:
            decision = await provider.extract(context, step_prompt, schema_hint=_TOOL_SCHEMA)
        except Exception as exc:
            logger.warning("agent_step_llm_failed", error=str(exc))
            steps.append(AgentStep(action="finish", reason=f"llm error: {type(exc).__name__}"))
            break

        action = str(decision.get("action", "")).lower()
        reason = str(decision.get("reason", ""))[:200]

        if action == "finish":
            data = decision.get("data")
            ok, err = _validate(data, json_schema)
            steps.append(AgentStep(action="finish", reason=reason))
            if ok:
                return AgentResponse(success=True, data=data, sources=sources, steps=steps, total_tokens=total_tokens)
            # Give the model one more chance by recording the error into context.
            context_parts.append(f"### Validation error\n{err}. Revise and finish again.")
            continue

        if action == "search":
            query = str(decision.get("query") or prompt)
            try:
                from pawgrab.engine.search_provider import search as run_search

                serp = await run_search(query, num_results=5)
                found = [r["link"] for r in serp.get("results", [])]
                found = [u for u in found if _domain_ok(u, allowed_domains)]
                context_parts.append("### Search results\n" + "\n".join(found))
                steps.append(AgentStep(action="search", query=query, reason=reason))
            except Exception as exc:
                steps.append(AgentStep(action="search", query=query, reason=f"search failed: {type(exc).__name__}"))
            continue

        if action == "fetch":
            url = decision.get("url")
            if not url:
                steps.append(AgentStep(action="fetch", reason="no url provided"))
                continue
            await _do_fetch(str(url), reason)
            continue

        steps.append(AgentStep(action=action or "unknown", reason="unrecognized action"))
        break

    # Budget exhausted without an explicit finish — make a final extraction attempt.
    if context_parts:
        try:
            data = await provider.extract(
                "\n\n".join(context_parts),
                f"{prompt}\n\nReturn the best answer you can from the content above as a JSON object.",
                schema_hint=json_schema,
            )
            ok, _ = _validate(data, json_schema)
            if ok:
                return AgentResponse(success=True, data=data, sources=sources, steps=steps, total_tokens=total_tokens)
        except Exception:
            pass

    return AgentResponse(
        success=False,
        data=None,
        sources=sources,
        steps=steps,
        total_tokens=total_tokens,
        error="agent exhausted its step budget without a valid result",
    )
