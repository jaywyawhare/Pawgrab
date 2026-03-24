"""Tests for the proxy pool: ProxyEntry, ProxyPool, and REST API."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from pawgrab.engine.proxy_pool import ProxyEntry, ProxyPool, RotationPolicy


class TestProxyEntry:
    def test_initial_state(self):
        e = ProxyEntry(url="http://p1:8080")
        assert e.ok is True
        assert e.speed == 0.0
        assert e.offered == 0
        assert e.succeed == 0
        assert e.failures == 0

    def test_mark_success(self):
        e = ProxyEntry(url="http://p1:8080")
        e.mark_success(speed=0.5)
        assert e.ok is True
        assert e.succeed == 1
        assert e.recent_succeed == 1
        assert e.speed == 0.5
        assert e.reanimate_after is None

    def test_mark_success_ema_speed(self):
        e = ProxyEntry(url="http://p1:8080")
        e.mark_success(speed=1.0)
        e.mark_success(speed=0.0)
        # EMA: 1.0 * 0.7 + 0.0 * 0.3 = 0.7
        assert round(e.speed, 2) == 0.7

    def test_mark_failure(self):
        e = ProxyEntry(url="http://p1:8080")
        e.mark_failure(is_timeout=False, backoff_seconds=30)
        assert e.ok is False
        assert e.failures == 1
        assert e.recent_failures == 1
        assert e.timeouts == 0
        assert e.reanimate_after is not None

    def test_mark_failure_timeout(self):
        e = ProxyEntry(url="http://p1:8080")
        e.mark_failure(is_timeout=True, backoff_seconds=30)
        assert e.timeouts == 1
        assert e.recent_timeouts == 1

    def test_should_skip_when_ok(self):
        e = ProxyEntry(url="http://p1:8080")
        assert e.should_skip(offer_limit=25) is False

    def test_should_skip_when_not_ok(self):
        e = ProxyEntry(url="http://p1:8080")
        e.ok = False
        e.reanimate_after = time.monotonic() + 9999  # far future
        assert e.should_skip(offer_limit=25) is True

    def test_should_skip_offer_limit(self):
        e = ProxyEntry(url="http://p1:8080")
        e.recent_offered = 25
        assert e.should_skip(offer_limit=25) is True

    def test_should_skip_reanimates_after_backoff(self):
        e = ProxyEntry(url="http://p1:8080")
        e.ok = False
        e.reanimate_after = time.monotonic() - 1  # backoff expired
        assert e.should_skip(offer_limit=25) is False
        assert e.ok is True
        assert e.reanimated == 1

    def test_should_evict(self):
        e = ProxyEntry(url="http://p1:8080")
        e.recent_succeed = 0
        e.recent_failures = 3
        assert e.should_evict(failure_threshold=3) is True

    def test_should_not_evict_with_successes(self):
        e = ProxyEntry(url="http://p1:8080")
        e.recent_succeed = 1
        e.recent_failures = 5
        assert e.should_evict(failure_threshold=3) is False

    def test_should_not_evict_below_threshold(self):
        e = ProxyEntry(url="http://p1:8080")
        e.recent_succeed = 0
        e.recent_failures = 2
        assert e.should_evict(failure_threshold=3) is False

    def test_snapshot(self):
        e = ProxyEntry(url="http://p1:8080")
        e.mark_success(speed=0.5)
        s = e.snapshot()
        assert s["url"] == "http://p1:8080"
        assert s["ok"] is True
        assert s["succeed"] == 1
        assert s["speed"] == 0.5


class TestProxyPool:
    @pytest.mark.asyncio
    async def test_add_remove(self):
        pool = ProxyPool()
        assert pool.add_proxy("http://p1:8080") is True
        assert pool.add_proxy("http://p1:8080") is False  # duplicate
        assert pool.remove_proxy("http://p1:8080") is True
        assert pool.remove_proxy("http://p1:8080") is False  # already removed
        await pool.stop()

    @pytest.mark.asyncio
    async def test_get_proxy_empty(self):
        pool = ProxyPool()
        result = await pool.get_proxy()
        assert result is None

    @pytest.mark.asyncio
    async def test_round_robin(self):
        pool = ProxyPool()
        pool._policy = RotationPolicy.ROUND_ROBIN
        pool.add_proxy("http://p1:8080")
        pool.add_proxy("http://p2:8080")

        e1 = await pool.get_proxy()
        e2 = await pool.get_proxy()
        assert e1.url == "http://p1:8080"
        assert e2.url == "http://p2:8080"

        e3 = await pool.get_proxy()
        assert e3.url == "http://p1:8080"  # wraps
        await pool.stop()

    @pytest.mark.asyncio
    async def test_random_policy(self):
        pool = ProxyPool()
        pool._policy = RotationPolicy.RANDOM
        pool.add_proxy("http://p1:8080")
        pool.add_proxy("http://p2:8080")

        results = set()
        for _ in range(20):
            e = await pool.get_proxy()
            results.add(e.url)
        assert len(results) >= 1  # at least one proxy selected
        await pool.stop()

    @pytest.mark.asyncio
    async def test_least_used(self):
        pool = ProxyPool()
        pool._policy = RotationPolicy.LEAST_USED
        pool.add_proxy("http://p1:8080")
        pool.add_proxy("http://p2:8080")

        # p1 gets offered first (both start at 0, min picks first)
        e1 = await pool.get_proxy()
        # Now p1 has offered=1, p2 has offered=0 → p2 next
        e2 = await pool.get_proxy()
        assert {e1.url, e2.url} == {"http://p1:8080", "http://p2:8080"}
        await pool.stop()

    @pytest.mark.asyncio
    async def test_skip_unhealthy(self):
        pool = ProxyPool()
        pool._policy = RotationPolicy.ROUND_ROBIN
        pool.add_proxy("http://p1:8080")
        pool.add_proxy("http://p2:8080")

        # Mark p1 as unhealthy
        pool._entries[0].ok = False
        pool._entries[0].reanimate_after = time.monotonic() + 9999

        e = await pool.get_proxy()
        assert e.url == "http://p2:8080"
        await pool.stop()

    @pytest.mark.asyncio
    async def test_all_unhealthy_returns_none(self):
        pool = ProxyPool()
        pool.add_proxy("http://p1:8080")
        pool._entries[0].ok = False
        pool._entries[0].reanimate_after = time.monotonic() + 9999

        result = await pool.get_proxy()
        assert result is None
        await pool.stop()

    @pytest.mark.asyncio
    async def test_pool_stats(self):
        pool = ProxyPool()
        pool.add_proxy("http://p1:8080")
        pool.add_proxy("http://p2:8080")
        pool._entries[1].ok = False

        stats = pool.pool_stats()
        assert stats["total"] == 2
        assert stats["active"] == 1
        assert stats["evicted"] == 1
        assert stats["policy"] == "round_robin"
        await pool.stop()

    @pytest.mark.asyncio
    async def test_snapshot(self):
        pool = ProxyPool()
        pool.add_proxy("http://p1:8080")
        snap = pool.snapshot()
        assert len(snap) == 1
        assert snap[0]["url"] == "http://p1:8080"
        await pool.stop()

    @pytest.mark.asyncio
    async def test_start_loads_from_settings(self):
        with patch("pawgrab.engine.proxy_pool.settings") as mock_settings:
            mock_settings.proxy_urls = "http://a:1,http://b:2"
            mock_settings.proxy_url = ""
            mock_settings.proxy_rotation_policy = "random"
            mock_settings.proxy_health_check = False
            mock_settings.proxy_offer_limit = 25
            mock_settings.proxy_evict_after_failures = 3
            mock_settings.proxy_backoff_seconds = 60

            pool = ProxyPool()
            await pool.start()
            assert len(pool._entries) == 2
            assert pool._policy == RotationPolicy.RANDOM
            await pool.stop()


@pytest.mark.asyncio
async def test_proxy_api_add_list_remove_stats():
    """Test the proxy pool REST endpoints via ASGI client."""
    # Reset the singleton so we get a fresh pool
    import pawgrab.dependencies as deps
    deps._proxy_pool = None

    import httpx

    from pawgrab.main import app

    with patch("pawgrab.engine.proxy_pool.settings") as mock_settings:
        mock_settings.proxy_urls = ""
        mock_settings.proxy_url = ""
        mock_settings.proxy_rotation_policy = "round_robin"
        mock_settings.proxy_health_check = False
        mock_settings.proxy_offer_limit = 25
        mock_settings.proxy_evict_after_failures = 3
        mock_settings.proxy_backoff_seconds = 60

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Add
            r = await client.post("/v1/proxy/pool", json={"url": "http://proxy1:8080"})
            assert r.status_code == 200
            assert r.json()["success"] is True

            # Add duplicate
            r = await client.post("/v1/proxy/pool", json={"url": "http://proxy1:8080"})
            assert r.json()["success"] is False

            # List
            r = await client.get("/v1/proxy/pool")
            assert r.status_code == 200
            proxies = r.json()["proxies"]
            assert len(proxies) == 1
            assert proxies[0]["url"] == "http://proxy1:8080"

            # Stats
            r = await client.get("/v1/proxy/pool/stats")
            assert r.status_code == 200
            stats = r.json()
            assert stats["total"] == 1
            assert stats["active"] == 1

            # Remove
            r = await client.delete("/v1/proxy/pool/http://proxy1:8080")
            assert r.status_code == 200

            # Remove non-existent
            r = await client.delete("/v1/proxy/pool/http://nope:1234")
            assert r.status_code == 404

    # Cleanup
    await deps.shutdown_proxy_pool()


@pytest.mark.asyncio
async def test_fetch_page_uses_proxy_pool():
    """fetch_page should get proxy from pool and mark success on result."""
    from pawgrab.engine.fetcher import FetchResult, fetch_page

    mock_entry = ProxyEntry(url="http://pool-proxy:8080")
    mock_pool = AsyncMock()
    mock_pool.get_proxy = AsyncMock(return_value=mock_entry)

    mock_result = FetchResult(html="<html>OK</html>", status_code=200, url="https://example.com")

    with patch("pawgrab.engine.fetcher._fetch_with_curl", new_callable=AsyncMock, return_value=mock_result) as mock_curl:
        _result = await fetch_page("https://example.com", proxy_pool=mock_pool)
        # Verify proxy was passed to curl
        call_kwargs = mock_curl.call_args
        assert call_kwargs.kwargs.get("proxy") == "http://pool-proxy:8080"
        # Verify success was marked
        assert mock_entry.succeed == 1
        assert mock_entry.ok is True


@pytest.mark.asyncio
async def test_fetch_page_marks_failure_on_exception():
    """fetch_page should mark proxy failure when curl raises."""
    from pawgrab.engine.fetcher import fetch_page

    mock_entry = ProxyEntry(url="http://pool-proxy:8080")
    mock_pool = AsyncMock()
    mock_pool.get_proxy = AsyncMock(return_value=mock_entry)

    with patch("pawgrab.engine.fetcher._fetch_with_curl", new_callable=AsyncMock, side_effect=Exception("timeout")):
        with pytest.raises(Exception, match="timeout"):
            await fetch_page("https://example.com", proxy_pool=mock_pool)
        # Verify failure was marked
        assert mock_entry.ok is False
        assert mock_entry.failures == 1


@pytest.mark.asyncio
async def test_fetch_page_works_without_proxy_pool():
    """fetch_page should work fine when proxy_pool is None."""
    from pawgrab.engine.fetcher import FetchResult, fetch_page

    mock_result = FetchResult(html="<html>OK</html>", status_code=200, url="https://example.com")
    with patch("pawgrab.engine.fetcher._fetch_with_curl", new_callable=AsyncMock, return_value=mock_result) as mock_curl:
        _result = await fetch_page("https://example.com")
        call_kwargs = mock_curl.call_args
        assert call_kwargs.kwargs.get("proxy") is None
