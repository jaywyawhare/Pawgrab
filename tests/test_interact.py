"""Tests for live interactive sessions (F3)."""

from unittest.mock import AsyncMock, patch

import pytest

from pawgrab.engine import live_session


class FakePage:
    def __init__(self, url="https://example.com"):
        self.url = url
        self._html = "<html><head><title>Hi</title></head><body><article><h1>Hello</h1><p>World content here.</p></article></body></html>"
        self.goto_calls = []

    async def goto(self, url, **kw):
        self.goto_calls.append(url)
        self.url = url

    async def content(self):
        return self._html

    async def screenshot(self, **kw):
        return b"\x89PNG\r\n\x1a\nFAKE"


class FakePool:
    def __init__(self):
        self.released = []
        self.page = FakePage()

    async def new_isolated_page(self):
        return self.page

    async def release_isolated_page(self, page):
        self.released.append(page)


@pytest.fixture(autouse=True)
def _clear_sessions():
    live_session._LIVE.clear()
    yield
    live_session._LIVE.clear()


async def test_start_keeps_page_alive_and_renders():
    pool = FakePool()
    scrape_id, rendered = await live_session.start(pool, "https://example.com", 30_000, ["markdown"])
    assert scrape_id in live_session._LIVE
    assert "Hello" in rendered["markdown"]
    assert pool.released == []  # page NOT released — it's kept alive


async def test_interact_code_runs_actions_and_rerenders():
    from pawgrab.models.scrape import ActionType, PageAction

    pool = FakePool()
    scrape_id, _ = await live_session.start(pool, "https://example.com", 30_000, ["markdown"])
    # A WAIT action needs no real DOM, so it exercises the executor safely.
    out = await live_session.interact_code(scrape_id, [PageAction(type=ActionType.WAIT, amount=1)], 30_000, ["markdown"])
    assert "markdown" in out
    assert out["action_warnings"] == []


async def test_interact_missing_session_raises():
    with pytest.raises(KeyError):
        await live_session.interact_code("nope", [], 30_000, ["markdown"])


async def test_screenshot_and_close():
    pool = FakePool()
    scrape_id, _ = await live_session.start(pool, "https://example.com", 30_000, ["markdown"])
    png = await live_session.screenshot(scrape_id)
    assert png.startswith(b"\x89PNG")
    assert await live_session.close(scrape_id) is True
    assert pool.page in pool.released
    assert await live_session.close(scrape_id) is False  # already gone


async def test_ttl_reaps_idle_session(monkeypatch):
    pool = FakePool()
    monkeypatch.setattr(live_session.settings, "live_session_ttl", 0)
    scrape_id, _ = await live_session.start(pool, "https://example.com", 30_000, ["markdown"])
    # next access triggers reap (ttl=0 => immediately idle)
    assert live_session.exists(scrape_id) is False


async def test_interact_ai_plans_actions():
    pool = FakePool()
    scrape_id, _ = await live_session.start(pool, "https://example.com", 30_000, ["markdown"])

    class P:
        async def extract(self, content, prompt, schema_hint=None, json_schema=None):
            return {"actions": [{"type": "wait", "amount": 1}]}

    with patch("pawgrab.ai.extractor.get_provider", return_value=P()):
        out = await live_session.interact_ai(scrape_id, "wait a moment", 30_000, ["markdown"])
    assert out["planned_actions"][0]["type"] == "wait"


async def test_start_live_endpoint(client):
    pool = FakePool()
    with patch("pawgrab.api.interact.try_browser_pool", new_callable=AsyncMock, return_value=pool):
        resp = await client.post("/scrape/live", json={"url": "https://example.com", "formats": ["markdown"]})
    data = resp.json()
    assert resp.status_code == 200
    assert data["scrape_id"]
    assert data["live_view_url"].endswith("/live.png")


async def test_start_live_endpoint_503_without_pool(client):
    with patch("pawgrab.api.interact.try_browser_pool", new_callable=AsyncMock, return_value=None):
        resp = await client.post("/scrape/live", json={"url": "https://example.com"})
    assert resp.status_code == 503
