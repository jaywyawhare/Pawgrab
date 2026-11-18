"""Tests for the agentic extractor (F1)."""

from unittest.mock import AsyncMock, patch

import pytest

from pawgrab.ai import agent as agent_mod
from pawgrab.models.agent import Effort


class ScriptedProvider:
    """Returns a queued sequence of decisions, then repeats the last one."""

    def __init__(self, decisions):
        self._decisions = list(decisions)
        self.calls = 0

    async def extract(self, content, prompt, schema_hint=None, json_schema=None):
        self.calls += 1
        if self._decisions:
            return self._decisions.pop(0)
        return {"action": "finish", "reason": "done", "data": {}}


async def _run(decisions, **kw):
    provider = ScriptedProvider(decisions)
    with patch("pawgrab.ai.extractor.get_provider", return_value=provider):
        with patch("pawgrab.ai.agent._fetch_markdown", new_callable=AsyncMock) as fetch:
            fetch.return_value = "# Page\nSome content about pricing: $10/mo."
            result = (
                await agent_mod.run_agent(
                    prompt=kw.get("prompt", "find the price"),
                    urls=kw.get("urls", []),
                    json_schema=kw.get("json_schema"),
                    effort=kw.get("effort", Effort.LOW),
                    max_steps=kw.get("max_steps"),
                    allowed_domains=kw.get("allowed_domains", []),
                    timeout=30_000,
                ),
                fetch,
            )
    return result


async def test_finish_returns_data():
    ((result, _),) = [await _run([{"action": "finish", "reason": "have it", "data": {"price": "$10/mo"}}])]
    assert result.success is True
    assert result.data == {"price": "$10/mo"}


async def test_fetch_then_finish_records_sources():
    result, fetch = await _run(
        [
            {"action": "fetch", "url": "https://example.com/pricing", "reason": "read pricing"},
            {"action": "finish", "reason": "done", "data": {"price": "$10/mo"}},
        ],
    )
    assert result.success is True
    assert "https://example.com/pricing" in result.sources
    fetch.assert_awaited()


async def test_offdomain_fetch_rejected():
    result, _ = await _run(
        [
            {"action": "fetch", "url": "https://evil.com/x", "reason": "nope"},
            {"action": "finish", "reason": "done", "data": {"ok": True}},
        ],
        allowed_domains=["example.com"],
    )
    assert "https://evil.com/x" not in result.sources
    assert any("rejected" in s.reason for s in result.steps)


async def test_budget_respected_low_effort():
    # Never finishes; low effort = 3 steps. Should stop and not loop forever.
    always_fetch = [{"action": "fetch", "url": f"https://example.com/{i}", "reason": "x"} for i in range(50)]
    with patch("pawgrab.config.settings.agent_steps_low", 3):
        result, _ = await _run(always_fetch, effort=Effort.LOW)
    # at most 3 loop iterations' worth of fetch steps
    fetch_steps = [s for s in result.steps if s.action == "fetch"]
    assert len(fetch_steps) <= 3


async def test_schema_validation_failure_then_retry():
    pytest.importorskip("jsonschema")
    schema = {"type": "object", "required": ["price"], "properties": {"price": {"type": "string"}}}
    result, _ = await _run(
        [
            {"action": "finish", "reason": "bad", "data": {"wrong": 1}},  # fails schema
            {"action": "finish", "reason": "good", "data": {"price": "$10/mo"}},  # passes
        ],
        json_schema=schema,
        effort=Effort.MEDIUM,
    )
    assert result.success is True
    assert result.data == {"price": "$10/mo"}


async def test_agent_endpoint_503_without_provider(client):
    with patch("pawgrab.ai.extractor.get_provider", side_effect=RuntimeError("no provider")):
        resp = await client.post("/agent", json={"prompt": "x"})
    assert resp.status_code == 503
    assert resp.json()["code"] == "llm_unavailable"
