"""Tests for the smart rendering cache in detector.py."""

import time

from pawgrab.engine.detector import (
    _cache,
    _RenderingCache,
    _run_heuristics,
    needs_js_rendering,
)


class TestRenderingCache:
    def setup_method(self):
        _cache.clear()

    def test_cache_hit(self):
        """Cached domain returns stored value without re-running heuristics."""
        # First call — runs heuristics and caches
        html = "<html><body><p>" + ("Hello world. " * 50) + "</p></body></html>"
        result1 = needs_js_rendering(html, url="https://example.com/page1")
        assert result1 is False

        # Second call with different HTML but same domain — should use cache
        result2 = needs_js_rendering("", url="https://example.com/page2")
        assert result2 is False  # cached as False, not re-evaluated

    def test_cache_miss_different_domain(self):
        """Different domains are cached independently."""
        html = "<html><body><p>" + ("Content. " * 50) + "</p></body></html>"
        needs_js_rendering(html, url="https://example.com/page")

        # Different domain — cache miss, runs heuristics on empty HTML
        result = needs_js_rendering("", url="https://other.com/page")
        assert result is True  # empty HTML → needs JS

    def test_ttl_expiry(self):
        """Cache entries expire after TTL."""
        cache = _RenderingCache(ttl=1)
        cache.put("example.com", False)
        assert cache.get("example.com") is False

        # Simulate TTL expiry
        cache._data["example.com"] = (False, time.monotonic() - 2)
        assert cache.get("example.com") is None

    def test_lru_eviction(self):
        """Oldest entries are evicted when cache is full."""
        cache = _RenderingCache(max_size=3)
        cache.put("a.com", True)
        cache.put("b.com", False)
        cache.put("c.com", True)
        cache.put("d.com", False)  # should evict a.com

        assert cache.get("a.com") is None
        assert cache.get("b.com") is False
        assert cache.get("d.com") is False

    def test_no_caching_without_url(self):
        """When no URL is provided, caching is skipped."""
        html = "<html><body><p>" + ("Content. " * 50) + "</p></body></html>"
        result = needs_js_rendering(html)
        assert result is False
        # Cache should remain empty
        assert len(_cache._data) == 0


class TestFrameworkDetection:
    def test_next_data(self):
        assert _run_heuristics('<script id="__NEXT_DATA__">{}') is True

    def test_nuxt(self):
        assert _run_heuristics("<script>window.__NUXT__={}") is True

    def test_gatsby(self):
        assert _run_heuristics('<div id="gatsby-focus-wrapper">') is True

    def test_static_page(self):
        html = "<html><body><p>" + ("This is a normal page. " * 30) + "</p></body></html>"
        assert _run_heuristics(html) is False
