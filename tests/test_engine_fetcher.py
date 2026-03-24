"""Tests for the fetcher module (mocked HTTP)."""

from unittest.mock import AsyncMock, patch

import pytest

from pawgrab.engine.fetcher import (
    _CF_MIN_TIMEOUT,
    FetchResult,
    _backoff,
    _check_challenge,
    _parse_retry_after,
    _sanitize_headers,
    fetch_page,
    is_proxy_error,
)


def _make_result(html="<html>OK</html>", status=200, url="https://example.com"):
    return FetchResult(html=html, status_code=status, url=url)


def test_fetch_result_slots():
    r = _make_result()
    assert r.html == "<html>OK</html>"
    assert r.status_code == 200
    assert r.url == "https://example.com"
    assert r.used_browser is False
    assert r.challenge is None
    assert r.resp_headers == {}
    assert r.cookies == {}


def test_fetch_result_with_browser():
    r = FetchResult(html="", status_code=200, url="https://x.com", used_browser=True)
    assert r.used_browser is True


def test_check_challenge_clean():
    r = _make_result()
    c = _check_challenge(r)
    assert c.detected is False


def test_check_challenge_detected():
    r = _make_result(
        html='<script src="/cdn-cgi/challenge-platform/x/orchestrate/jsch/v1"></script>',
        status=403,
    )
    r.resp_headers = {"server": "cloudflare"}
    c = _check_challenge(r)
    assert c.detected is True


def test_sanitize_headers_removes_host():
    result = _sanitize_headers({"Host": "evil.com", "Accept": "text/html"})
    assert "Host" not in result
    assert result["Accept"] == "text/html"


def test_sanitize_headers_removes_transfer_encoding():
    result = _sanitize_headers({"Transfer-Encoding": "chunked", "X-Custom": "ok"})
    assert "Transfer-Encoding" not in result
    assert result["X-Custom"] == "ok"


def test_sanitize_headers_case_insensitive():
    result = _sanitize_headers({"host": "evil.com", "HOST": "evil.com", "Content-Length": "0"})
    assert len(result) == 0


def test_sanitize_headers_none():
    assert _sanitize_headers(None) is None


def test_sanitize_headers_empty():
    assert _sanitize_headers({}) == {}


def test_sanitize_headers_allows_safe_headers():
    headers = {"Accept-Language": "en", "X-Custom": "value", "Cookie": "a=b"}
    result = _sanitize_headers(headers)
    assert result == headers


@pytest.mark.asyncio
async def test_fetch_page_uses_curl():
    mock_result = _make_result()
    with patch("pawgrab.engine.fetcher._fetch_with_curl", new_callable=AsyncMock, return_value=mock_result):
        result = await fetch_page("https://example.com")
    assert result.html == "<html>OK</html>"
    assert result.used_browser is False


@pytest.mark.asyncio
async def test_fetch_page_sanitizes_headers():
    """Dangerous headers should be stripped before fetching."""
    mock_result = _make_result()
    with patch("pawgrab.engine.fetcher._fetch_with_curl", new_callable=AsyncMock, return_value=mock_result) as mock_curl:
        await fetch_page(
            "https://example.com",
            headers={"Host": "evil.com", "Accept": "text/html"},
        )
        call_kwargs = mock_curl.call_args
        passed_headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert "Host" not in passed_headers
        assert passed_headers["Accept"] == "text/html"


@pytest.mark.asyncio
async def test_fetch_page_proxy_pool_passes_proxy():
    """When proxy_pool is provided, its proxy URL should be passed to curl."""
    from pawgrab.engine.proxy_pool import ProxyEntry

    mock_entry = ProxyEntry(url="http://p1:8080")
    mock_pool = AsyncMock()
    mock_pool.get_proxy = AsyncMock(return_value=mock_entry)

    mock_result = _make_result()
    with patch("pawgrab.engine.fetcher._fetch_with_curl", new_callable=AsyncMock, return_value=mock_result) as mock_curl:
        await fetch_page("https://example.com", proxy_pool=mock_pool)
        call_kwargs = mock_curl.call_args
        assert call_kwargs.kwargs.get("proxy") == "http://p1:8080"


@pytest.mark.asyncio
async def test_fetch_page_no_proxy_pool():
    """Without proxy_pool, no proxy should be passed."""
    mock_result = _make_result()
    with patch("pawgrab.engine.fetcher._fetch_with_curl", new_callable=AsyncMock, return_value=mock_result) as mock_curl:
        await fetch_page("https://example.com")
        call_kwargs = mock_curl.call_args
        assert call_kwargs.kwargs.get("proxy") is None


@pytest.mark.asyncio
async def test_backoff_no_delay_first_attempt():
    """First attempt should not backoff."""
    import time
    start = time.monotonic()
    await _backoff(1)
    elapsed = time.monotonic() - start
    assert elapsed < 0.1


@pytest.mark.asyncio
async def test_backoff_delays_on_retry():
    """Second+ attempt should delay."""
    import time
    start = time.monotonic()
    await _backoff(2)
    elapsed = time.monotonic() - start
    assert elapsed >= 1.0  # 2^(2-1) = 2s base, but with jitter at least 1s


@pytest.mark.asyncio
async def test_fetch_page_injects_referer():
    """fetch_page should add a Referer header when none provided."""
    mock_result = _make_result()
    with patch("pawgrab.engine.fetcher._fetch_with_curl", new_callable=AsyncMock, return_value=mock_result) as mock_curl:
        with patch("pawgrab.engine.fetcher.random_referer", return_value="https://www.google.com/"):
            await fetch_page("https://example.com")
            call_kwargs = mock_curl.call_args
            passed_headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
            assert passed_headers.get("Referer") == "https://www.google.com/"


def test_fetch_result_stores_cookies():
    r = FetchResult(html="", status_code=200, url="https://x.com", cookies={"cf_clearance": "abc"})
    assert r.cookies == {"cf_clearance": "abc"}


def test_check_challenge_silent_block():
    """403 with tiny body = silent block."""
    r = FetchResult(html="Forbidden", status_code=403, url="https://x.com")
    c = _check_challenge(r)
    assert c.detected is True
    assert c.challenge_type == "silent_block"


def test_check_challenge_no_silent_block_on_normal_403():
    """403 with substantial body should not trigger silent block."""
    r = FetchResult(html="<html>" + "x" * 1000 + "</html>", status_code=403, url="https://x.com")
    c = _check_challenge(r)
    # Should not be detected as silent block (body > 500 chars)
    assert c.challenge_type != "silent_block"


def test_check_challenge_cf_mitigated_header():
    """cf-mitigated: challenge header should trigger detection."""
    r = FetchResult(html="<html>OK</html>", status_code=200, url="https://x.com")
    r.resp_headers = {"cf-mitigated": "challenge"}
    c = _check_challenge(r)
    assert c.detected is True
    assert c.challenge_type == "cloudflare_mitigated"


def test_parse_retry_after_429():
    r = FetchResult(html="", status_code=429, url="https://x.com")
    r.resp_headers = {"Retry-After": "5"}
    assert _parse_retry_after(r) == 5.0


def test_parse_retry_after_non_429():
    r = FetchResult(html="", status_code=200, url="https://x.com")
    r.resp_headers = {"Retry-After": "5"}
    assert _parse_retry_after(r) is None


def test_parse_retry_after_missing():
    r = FetchResult(html="", status_code=429, url="https://x.com")
    r.resp_headers = {}
    assert _parse_retry_after(r) is None


def test_is_proxy_error_detects_net_err_proxy():
    exc = Exception("net::ERR_PROXY_CONNECTION_FAILED")
    assert is_proxy_error(exc) is True


def test_is_proxy_error_detects_connection_refused():
    exc = Exception("Connection refused by proxy")
    assert is_proxy_error(exc) is True


def test_is_proxy_error_detects_tunnel_error():
    exc = Exception("net::ERR_TUNNEL_CONNECTION_FAILED")
    assert is_proxy_error(exc) is True


def test_is_proxy_error_false_for_normal_timeout():
    exc = Exception("Timeout 30000ms exceeded")
    assert is_proxy_error(exc) is False


def test_is_proxy_error_false_for_generic_error():
    exc = Exception("Page crashed")
    assert is_proxy_error(exc) is False

def test_cf_min_timeout_value():
    assert _CF_MIN_TIMEOUT == 60_000
