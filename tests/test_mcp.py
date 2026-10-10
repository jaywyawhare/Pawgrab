"""Tests for the MCP HTTP client behind the Pawgrab MCP tools."""

import httpx
import pytest

from pawgrab.config import settings
from pawgrab.mcp import client


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, raise_json=False):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("not json")
        return self._payload


class _FakeClient:
    """Stand-in for httpx.AsyncClient that records the last request."""

    calls: list[dict] = []
    response: _FakeResponse = _FakeResponse()
    raise_exc: Exception | None = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def request(self, method, url, json=None, headers=None):
        _FakeClient.calls.append({"method": method, "url": url, "json": json, "headers": headers})
        if _FakeClient.raise_exc is not None:
            raise _FakeClient.raise_exc
        return _FakeClient.response


@pytest.fixture(autouse=True)
def _patch_client(monkeypatch):
    _FakeClient.calls = []
    _FakeClient.response = _FakeResponse(200, {"success": True})
    _FakeClient.raise_exc = None
    monkeypatch.setattr(client.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(settings, "mcp_api_url", "http://localhost:8000")
    monkeypatch.setattr(settings, "api_key", "")
    yield


async def test_scrape_posts_to_v1_scrape():
    _FakeClient.response = _FakeResponse(200, {"success": True, "markdown": "# Hi"})
    out = await client.scrape("https://example.com", formats=["markdown"], wait_for_js=True)
    call = _FakeClient.calls[-1]
    assert call["method"] == "POST"
    assert call["url"] == "http://localhost:8000/v1/scrape"
    assert call["json"] == {"url": "https://example.com", "timeout": 30000, "formats": ["markdown"], "wait_for_js": True}
    assert out["markdown"] == "# Hi"


async def test_crawl_and_status_paths():
    _FakeClient.response = _FakeResponse(202, {"job_id": "abc"})
    await client.crawl("https://example.com", max_pages=5)
    assert _FakeClient.calls[-1]["url"] == "http://localhost:8000/v1/crawl"
    assert _FakeClient.calls[-1]["json"] == {"url": "https://example.com", "max_pages": 5, "max_depth": 2}

    _FakeClient.response = _FakeResponse(200, {"status": "completed"})
    await client.crawl_status("abc")
    assert _FakeClient.calls[-1]["method"] == "GET"
    assert _FakeClient.calls[-1]["url"] == "http://localhost:8000/v1/crawl/abc"


async def test_extract_forwards_adaptive_and_selectors():
    await client.extract("https://e.com", strategy="css", selectors={"t": "h1"}, adaptive=True)
    assert _FakeClient.calls[-1]["json"] == {
        "url": "https://e.com",
        "strategy": "css",
        "adaptive": True,
        "selectors": {"t": "h1"},
    }


async def test_auth_header_sent_when_api_key_set(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret")
    await client.scrape("https://example.com")
    assert _FakeClient.calls[-1]["headers"]["Authorization"] == "Bearer secret"


async def test_no_auth_header_without_api_key():
    await client.scrape("https://example.com")
    assert "Authorization" not in _FakeClient.calls[-1]["headers"]


async def test_transport_error_becomes_structured_error():
    _FakeClient.raise_exc = httpx.ConnectError("refused")
    out = await client.scrape("https://example.com")
    assert out["code"] == "api_unreachable"
    assert "refused" in out["error"]


async def test_http_error_status_gets_error_field():
    _FakeClient.response = _FakeResponse(503, {"success": False})
    out = await client.scrape("https://example.com")
    assert out["error"] == "HTTP 503"


async def test_non_json_response_is_handled():
    _FakeClient.response = _FakeResponse(200, raise_json=True)
    out = await client.scrape("https://example.com")
    assert out["code"] == "bad_response"


async def test_base_url_trailing_slash_normalized(monkeypatch):
    monkeypatch.setattr(settings, "mcp_api_url", "http://localhost:8000/")
    await client.map_site("https://example.com")
    assert _FakeClient.calls[-1]["url"] == "http://localhost:8000/v1/map"


async def test_server_registers_all_tools():
    pytest.importorskip("mcp")
    from pawgrab.mcp.server import build_server

    server = build_server()
    tools = await server.list_tools()
    assert {t.name for t in tools} == {
        "scrape",
        "parse",
        "extract",
        "search",
        "map_site",
        "crawl",
        "crawl_status",
    }
