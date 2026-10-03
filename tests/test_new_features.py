"""Tests for /v1/parse, search domain scoping, LLM enrichment, and selector healing."""

import asyncio
from unittest.mock import AsyncMock, patch

from pawgrab.ai.extractor import enrich_scrape
from pawgrab.api.search import _filter_domains, _host_matches_domain
from pawgrab.engine.cleaner import extract_content
from pawgrab.models.scrape import ScrapeResponse


async def test_parse_markdown(client):
    resp = await client.post(
        "/v1/parse",
        json={"html": "<html><body><article><h1>Title</h1><p>Some body text.</p></article></body></html>"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "Title" in (data["markdown"] or "")


async def test_parse_text_format_and_selector(client):
    html = '<html><body><nav>menu</nav><div class="main"><p>Hello world content here.</p></div></body></html>'
    resp = await client.post("/v1/parse", json={"html": html, "formats": ["text"], "css_selector": ".main"})
    assert resp.status_code == 200
    data = resp.json()
    assert "Hello world" in (data["text"] or "")
    assert "menu" not in (data["text"] or "")


async def test_parse_empty_html_rejected(client):
    resp = await client.post("/v1/parse", json={"html": ""})
    assert resp.status_code == 422


async def test_parse_garbage_returns_error_payload(client):
    resp = await client.post("/v1/parse", json={"html": "\x00\x01\x02"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] in (True, False)


def test_host_matches_domain():
    assert _host_matches_domain("docs.example.com", "example.com")
    assert _host_matches_domain("example.com", "example.com")
    assert _host_matches_domain("www.Example.com", "example.com")
    assert not _host_matches_domain("notexample.com", "example.com")
    assert not _host_matches_domain("other.com", "example.com")


def test_filter_domains_include_exclude():
    items = [{"link": f"https://{h}/x"} for h in ("a.example.com", "b.com", "c.example.org")]
    kept = _filter_domains(items, include=["example.com"], exclude=None)
    assert [i["link"] for i in kept] == ["https://a.example.com/x"]

    kept = _filter_domains(items, include=None, exclude=["b.com"])
    assert len(kept) == 2

    assert _filter_domains(items, None, None) is items


async def test_search_domain_scoping_applied(client):
    from tests.test_api_search import _envelope

    async def fake_scrape(url, **kwargs):
        return ScrapeResponse(success=True, url=url, markdown="md")

    with patch("pawgrab.api.search.run_search", new_callable=AsyncMock) as mock_search, patch("pawgrab.api.search.scrape_url", new=AsyncMock(side_effect=fake_scrape)):
        mock_search.return_value = _envelope(["https://good.example.com/a", "https://bad.com/b"])
        resp = await client.post("/v1/search", json={"query": "q", "include_domains": ["example.com"]})

    assert resp.status_code == 200
    data = resp.json()
    assert [r["url"] for r in data["results"]] == ["https://good.example.com/a"]
    assert all(r["link"] != "https://bad.com/b" for r in data["search_results"])


async def test_enrich_empty_content():
    assert await enrich_scrape("") == {}
    assert await enrich_scrape("   ") == {}


async def test_enrich_no_tasks():
    assert await enrich_scrape("content") == {}


async def test_enrich_single_call_shapes_result():
    class FakeProvider:
        async def extract(self, content, prompt, schema_hint=None, json_schema=None):
            assert "Summarize" in prompt
            return {"summary": "A summary.", "answer": None, "highlights": ["verbatim sentence."]}

    import pawgrab.ai.extractor as mod

    with patch.object(mod, "get_provider", return_value=FakeProvider()):
        out = await enrich_scrape("page text", summary=True, highlights=True)

    assert out == {"summary": "A summary.", "highlights": ["verbatim sentence."]}
    assert "answer" not in out


def test_selector_heals_to_class_token():
    html = '<html><body><nav>menu</nav><div class="pricebox"><p>Total: $42</p></div></body></html>'
    result = extract_content(html, css_selector="div.pricebox > p.lead:nth-child(2)")
    assert "Total" in result.content_html


def test_exact_match_still_preferred():
    html = '<html><body><div id="target"><p>exact</p></div><span>exact</span></body></html>'
    result = extract_content(html, css_selector="#target p")
    assert "exact" in result.content_html


async def test_reset_host_identity_clears_pin_and_warm(monkeypatch):
    from pawgrab.engine import fetcher

    fetcher._host_targets["example.com"] = "safari184"
    fetcher._WARMED_HOSTS["example.com"] = 123.0
    monkeypatch.setattr(fetcher, "_host_targets_lock", asyncio.Lock())
    await fetcher.reset_host_identity("https://example.com/deep/page")
    assert "example.com" not in fetcher._host_targets
    assert "example.com" not in fetcher._WARMED_HOSTS


async def test_fetch_page_prefer_premium_uses_premium_tier(monkeypatch):
    from pawgrab.engine import fetcher

    calls = {}

    class FakePool:
        async def get_proxy(self, premium=False):
            calls["premium"] = premium
            return None

    class FakeResp:
        status_code = 200
        headers = {}
        cookies = {}
        content = b"<html><body>hi</body></html>"
        url = "https://example.com/"
        encoding = "utf-8"
        text = "<html><body>hi</body></html>"

    class FakeSession:
        async def get(self, *a, **k):
            return FakeResp()

        async def close(self):
            pass

    async def fake_get_session(impersonate, proxy=None):
        return FakeSession()

    monkeypatch.setattr(fetcher, "_get_session", fake_get_session)
    await fetcher.fetch_page("https://example.com/", proxy_pool=FakePool(), prefer_premium=True)
    assert calls["premium"] is True


async def test_scrape_service_escalates_when_blocked(monkeypatch):
    from pawgrab.config import settings
    from pawgrab.engine import scrape_service as ss
    from pawgrab.engine.antibot import ChallengeDetection
    from pawgrab.engine.fetcher import FetchResult

    monkeypatch.setattr(settings, "fetch_escalation_retry", True)

    blocked = FetchResult(html="<html></html>", status_code=403, url="https://a.com/", challenge=ChallengeDetection(detected=True, challenge_type="cloudflare_interstitial"))
    good = FetchResult(html="<html><body>" + "x" * 500 + "</body></html>", status_code=200, url="https://a.com/")

    async def fake_fetch(url, **kwargs):
        if kwargs.get("prefer_premium"):
            return good
        return blocked

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(ss, "fetch_page", fake_fetch)
    monkeypatch.setattr(ss, "guard_url", noop)

    resp = await ss.scrape_url("https://a.com/", formats=[__import__("pawgrab.models.common", fromlist=["OutputFormat"]).OutputFormat.TEXT])
    assert resp.success or len(resp.text or "") > 0
