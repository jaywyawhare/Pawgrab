"""Live interactive browser sessions (F3).

A ``keep_alive`` scrape parks its Patchright page here instead of releasing it, so
follow-up requests can drive the *same* live page (code actions or an AI prompt)
and read a live screenshot. Pages live in-process (they can't be serialized), keyed
by an opaque session id; a TTL reaps idle sessions.

Limitation: the page lives on the worker that created it, so in a multi-worker
deployment follow-ups must reach the same process (sticky routing or a single
browser worker). This is documented in docs/interact.md.
"""

from __future__ import annotations

import time
import uuid

import structlog

from pawgrab.config import settings
from pawgrab.engine.cleaner import extract_content
from pawgrab.engine.converter import html_to_markdown

logger = structlog.get_logger()

# scrape_id -> {page, pool, url, created, last_used}
_LIVE: dict[str, dict] = {}


async def _render_formats(page, url: str, formats: list[str]) -> dict:
    """Read the live page's current DOM and render the requested output formats."""
    html = await page.content()
    out: dict = {}
    cleaned = extract_content(html, url=url)
    if "html" in formats:
        out["html"] = html
    if "markdown" in formats or not formats:
        out["markdown"] = html_to_markdown(cleaned.content_html)
    if "text" in formats:
        out["text"] = cleaned.text if hasattr(cleaned, "text") else html_to_markdown(cleaned.content_html)
    out["title"] = getattr(cleaned, "title", "") or ""
    out["current_url"] = page.url
    return out


def _reap() -> None:
    """Drop expired sessions (lazy; called on each access)."""
    now = time.time()
    dead = [sid for sid, rec in _LIVE.items() if now - rec["last_used"] > settings.live_session_ttl]
    for sid in dead:
        rec = _LIVE.pop(sid, None)
        if rec:
            import asyncio

            try:
                asyncio.get_event_loop().create_task(_close_page(rec))
            except Exception:
                pass


async def _close_page(rec: dict) -> None:
    try:
        await rec["pool"].release_isolated_page(rec["page"])
    except Exception:
        pass


async def start(pool, url: str, timeout: int, formats: list[str]) -> tuple[str, dict]:
    """Open a live page at `url`, keep it, and return (session_id, rendered formats)."""
    _reap()
    if len(_LIVE) >= settings.live_session_max:
        raise RuntimeError("live session capacity reached")
    page = await pool.new_isolated_page()
    try:
        await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
    except Exception:
        await pool.release_isolated_page(page)
        raise
    scrape_id = uuid.uuid4().hex[:16]
    _LIVE[scrape_id] = {"page": page, "pool": pool, "url": url, "created": time.time(), "last_used": time.time()}
    rendered = await _render_formats(page, url, formats)
    logger.info("live_session_started", scrape_id=scrape_id, url=url)
    return scrape_id, rendered


def _get(scrape_id: str) -> dict | None:
    _reap()
    rec = _LIVE.get(scrape_id)
    if rec:
        rec["last_used"] = time.time()
    return rec


async def interact_code(scrape_id: str, actions: list, timeout: int, formats: list[str]) -> dict:
    """Run code actions against the live page and return the refreshed formats + log."""
    rec = _get(scrape_id)
    if rec is None:
        raise KeyError(scrape_id)
    from pawgrab.engine.actions import run_actions

    warnings = await run_actions(rec["page"], actions, timeout)
    rendered = await _render_formats(rec["page"], rec["url"], formats)
    rendered["action_warnings"] = warnings
    return rendered


_ACTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["click", "type", "scroll", "wait", "wait_for", "press_key", "select", "hover", "fill_form", "submit_form"]},
                    "selector": {"type": ["string", "null"]},
                    "text": {"type": ["string", "null"]},
                    "direction": {"type": ["string", "null"]},
                    "amount": {"type": ["integer", "null"]},
                },
                "required": ["type"],
            },
        }
    },
    "required": ["actions"],
}


async def interact_ai(scrape_id: str, prompt: str, timeout: int, formats: list[str]) -> dict:
    """Ask the LLM to turn a prompt into page actions, run them, return refreshed formats."""
    rec = _get(scrape_id)
    if rec is None:
        raise KeyError(scrape_id)
    from pawgrab.ai.extractor import get_provider
    from pawgrab.models.scrape import PageAction

    html = await rec["page"].content()
    provider = get_provider()
    decision = await provider.extract(
        html[:12_000],
        f"The user wants: {prompt}\nReturn a list of page actions (click/type/scroll/etc.) that accomplish this on the current page. Use CSS selectors visible in the HTML.",
        schema_hint=_ACTIONS_SCHEMA,
    )
    raw_actions = decision.get("actions", []) if isinstance(decision, dict) else []
    actions = []
    for a in raw_actions:
        try:
            actions.append(PageAction(**a))
        except Exception:
            continue
    from pawgrab.engine.actions import run_actions

    warnings = await run_actions(rec["page"], actions, timeout)
    rendered = await _render_formats(rec["page"], rec["url"], formats)
    rendered["action_warnings"] = warnings
    rendered["planned_actions"] = [a.model_dump() for a in actions]
    return rendered


async def screenshot(scrape_id: str) -> bytes:
    """Return a PNG screenshot of the live page (the liveViewUrl backing bytes)."""
    rec = _get(scrape_id)
    if rec is None:
        raise KeyError(scrape_id)
    return await rec["page"].screenshot(type="png")


async def close(scrape_id: str) -> bool:
    """Close and free a live session. Returns True if it existed."""
    rec = _LIVE.pop(scrape_id, None)
    if rec is None:
        return False
    await _close_page(rec)
    logger.info("live_session_closed", scrape_id=scrape_id)
    return True


def exists(scrape_id: str) -> bool:
    return _get(scrape_id) is not None


async def close_all() -> None:
    """Shut every live session down (called on app shutdown)."""
    for sid in list(_LIVE.keys()):
        await close(sid)
