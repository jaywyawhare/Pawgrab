"""Tests for the crawl worker — BFS logic, link extraction, depth limits."""

from urllib.parse import urlparse

from pawgrab.queue.worker import _extract_links, _is_noindex_page


def test_extract_links_same_domain():
    html = """
    <html><body>
        <a href="/page1">Page 1</a>
        <a href="https://example.com/page2">Page 2</a>
        <a href="https://other.com/page3">Other</a>
    </body></html>
    """
    links = _extract_links(html, "https://example.com", "https://example.com", set())
    assert "https://example.com/page1" in links
    assert "https://example.com/page2" in links
    assert "https://other.com/page3" not in links


def test_extract_links_skips_visited():
    html = '<html><body><a href="/page1">P</a><a href="/page2">P</a></body></html>'
    visited = {"https://example.com/page1"}
    links = _extract_links(html, "https://example.com", "https://example.com", visited)
    assert "https://example.com/page2" in links
    assert "https://example.com/page1" not in links


def test_extract_links_skips_non_http():
    html = """
    <html><body>
        <a href="mailto:test@test.com">Email</a>
        <a href="javascript:void(0)">JS</a>
        <a href="ftp://files.com/x">FTP</a>
        <a href="/valid">Valid</a>
    </body></html>
    """
    links = _extract_links(html, "https://example.com", "https://example.com", set())
    assert len(links) == 1
    assert "https://example.com/valid" in links


def test_extract_links_handles_empty_html():
    links = _extract_links("", "https://example.com", "https://example.com", set())
    assert links == []


def test_extract_links_handles_malformed_href():
    html = '<html><body><a href="">Empty</a><a>No href</a></body></html>'
    links = _extract_links(html, "https://example.com", "https://example.com", set())
    # Empty href resolves to base URL which is same domain, but no-href tags are skipped
    assert all(urlparse(link).scheme in ("http", "https") for link in links)


def test_extract_links_relative_urls():
    html = '<html><body><a href="../other/page">Rel</a></body></html>'
    links = _extract_links(html, "https://example.com/dir/current", "https://example.com", set())
    assert any("example.com" in link for link in links)


def test_extract_links_skips_hidden_display_none():
    html = """<html><body>
        <a href="/visible">Visible</a>
        <a href="/hidden" style="display:none">Hidden</a>
    </body></html>"""
    links = _extract_links(html, "https://example.com", "https://example.com", set())
    assert "https://example.com/visible" in links
    assert "https://example.com/hidden" not in links


def test_extract_links_skips_hidden_visibility():
    html = '<html><body><a href="/trap" style="visibility: hidden">Trap</a></body></html>'
    links = _extract_links(html, "https://example.com", "https://example.com", set())
    assert links == []


def test_extract_links_skips_hidden_opacity_zero():
    html = '<html><body><a href="/trap" style="opacity:0">Trap</a></body></html>'
    links = _extract_links(html, "https://example.com", "https://example.com", set())
    assert links == []


def test_extract_links_skips_aria_hidden():
    html = '<html><body><a href="/trap" aria-hidden="true">Trap</a></body></html>'
    links = _extract_links(html, "https://example.com", "https://example.com", set())
    assert links == []


def test_extract_links_skips_hidden_parent():
    html = """<html><body>
        <div style="display: none"><a href="/trap">Trap</a></div>
        <a href="/visible">Visible</a>
    </body></html>"""
    links = _extract_links(html, "https://example.com", "https://example.com", set())
    assert "https://example.com/visible" in links
    assert "https://example.com/trap" not in links


def test_is_noindex_page_detects_noindex():
    html = '<html><head><meta name="robots" content="noindex"></head><body>Trap</body></html>'
    assert _is_noindex_page(html) is True


def test_is_noindex_page_normal():
    html = "<html><head><title>Normal</title></head><body>OK</body></html>"
    assert _is_noindex_page(html) is False
