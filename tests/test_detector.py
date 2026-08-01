import time

import pytest

from pawgrab.engine.detector import (
    _extract_domain,
    _RenderingCache,
    _run_heuristics,
    needs_js_rendering,
)


class TestRenderingCache:
    def test_miss_returns_none(self):
        cache = _RenderingCache()
        assert cache.get("example.com") is None

    def test_put_and_get(self):
        cache = _RenderingCache()
        cache.put("example.com", True)
        assert cache.get("example.com") is True
        cache.put("other.com", False)
        assert cache.get("other.com") is False

    def test_expired_entry_returns_none(self):
        cache = _RenderingCache(ttl=0)
        cache.put("example.com", True)
        time.sleep(0.01)
        assert cache.get("example.com") is None

    def test_lru_eviction(self):
        cache = _RenderingCache(max_size=2)
        cache.put("a.com", True)
        cache.put("b.com", True)
        cache.put("c.com", True)
        assert cache.get("a.com") is None
        assert cache.get("b.com") is True
        assert cache.get("c.com") is True

    def test_access_promotes_entry(self):
        cache = _RenderingCache(max_size=2)
        cache.put("a.com", True)
        cache.put("b.com", True)
        cache.get("a.com")
        cache.put("c.com", True)
        assert cache.get("a.com") is True
        assert cache.get("b.com") is None
        assert cache.get("c.com") is True

    def test_clear(self):
        cache = _RenderingCache()
        cache.put("a.com", True)
        cache.put("b.com", False)
        cache.clear()
        assert cache.get("a.com") is None
        assert cache.get("b.com") is None


class TestExtractDomain:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://example.com/page", "example.com"),
            ("http://localhost:8080/path", "localhost:8080"),
            ("https://www.example.com", "www.example.com"),
            ("", ""),
        ],
    )
    def test_extract(self, url, expected):
        assert _extract_domain(url) == expected


class TestRunHeuristics:
    @pytest.mark.parametrize(
        "html",
        [
            '<html><body><div id="root"></div></body></html>',
            '<html><body><div id="app"></div></body></html>',
            "<html><head></head><body><script>window.__NEXT_DATA__ = {}</script></body></html>",
            "<html><body><script>window.__NUXT__ = {}</script></body></html>",
            "<html><body><noscript>Please enable JavaScript</noscript></body></html>",
            '<html><body><div></div><script src="/app.js"></script></body></html>',
            '<html><body><div id="gatsby-focus-wrapper"></div>' + "<p>" + "x" * 500 + "</p></body></html>",
        ],
    )
    def test_spa_returns_true(self, html):
        assert _run_heuristics(html) is True

    def test_short_static_page_without_scripts_is_not_js(self):
        # A small, complete static page (no scripts) must not be flagged as needing
        # JS — doing so fails valid terse pages at the scrape layer.
        assert _run_heuristics("<html><body><h1>Hello</h1><p>World</p></body></html>") is False

    def test_rich_static_content_returns_false(self):
        html = "<html><body>" + "<p>" + "x" * 500 + "</p>" + "</body></html>"
        assert _run_heuristics(html) is False


class TestNeedsJsRendering:
    def setup_method(self):
        from pawgrab.engine.detector import _cache

        _cache.clear()

    def test_spa_html_returns_true(self):
        assert needs_js_rendering('<html><body><div id="root"></div></body></html>') is True

    def test_static_html_returns_false(self):
        assert needs_js_rendering("<html><body>" + "<p>" + "x" * 500 + "</p></body></html>") is False

    def test_result_cached_by_domain(self):
        url = "https://spa.example.com/page"
        result1 = needs_js_rendering('<html><body><div id="root"></div></body></html>', url=url)
        result2 = needs_js_rendering("<html><body>" + "<p>" + "x" * 500 + "</p></body></html>", url=url)
        assert result1 == result2

    def test_no_url_skips_cache(self):
        assert needs_js_rendering('<html><body><div id="root"></div></body></html>') is True
        assert needs_js_rendering("<html><body>" + "<p>" + "x" * 500 + "</p></body></html>") is False
