from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pawgrab.engine.sitemap import _matches_domain, _parse_sitemap_xml


class TestParseSitemapXml:
    def test_basic_urlset(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/page1</loc></url>
  <url><loc>https://example.com/page2</loc></url>
</urlset>"""
        urls = _parse_sitemap_xml(xml)
        assert "https://example.com/page1" in urls
        assert "https://example.com/page2" in urls

    def test_sitemap_index(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap1.xml</loc></sitemap>
  <sitemap><loc>https://example.com/sitemap2.xml</loc></sitemap>
</sitemapindex>"""
        urls = _parse_sitemap_xml(xml)
        assert "https://example.com/sitemap1.xml" in urls
        assert "https://example.com/sitemap2.xml" in urls

    def test_without_namespace(self):
        xml = """<?xml version="1.0"?><urlset><url><loc>https://example.com/a</loc></url></urlset>"""
        assert "https://example.com/a" in _parse_sitemap_xml(xml)

    def test_limit_applied(self):
        items = "\n".join([f"<url><loc>https://example.com/{i}</loc></url>" for i in range(100)])
        xml = f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</urlset>'
        assert len(_parse_sitemap_xml(xml, limit=10)) == 10

    def test_invalid_xml_returns_empty(self):
        assert _parse_sitemap_xml("not xml at all") == []

    def test_empty_xml_returns_empty(self):
        assert _parse_sitemap_xml("") == []

    def test_strips_whitespace_from_urls(self):
        xml = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>  https://example.com/spaced  </loc></url>
</urlset>"""
        assert "https://example.com/spaced" in _parse_sitemap_xml(xml)


class TestMatchesDomain:
    @pytest.mark.parametrize(
        "url,domain,expected",
        [
            ("https://example.com/page", "example.com", True),
            ("https://other.com/page", "example.com", False),
            ("https://sub.example.com/page", "example.com", False),
            ("https://example.com:443/page", "example.com", True),
            ("not-a-url", "example.com", False),
        ],
    )
    def test_matches(self, url, domain, expected):
        assert _matches_domain(url, domain) is expected


@pytest.mark.asyncio
class TestDiscoverUrls:
    async def test_discover_from_sitemap(self):
        from pawgrab.engine.sitemap import discover_urls

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/page1</loc></url>
  <url><loc>https://example.com/page2</loc></url>
</urlset>"""
        mock_session.get = AsyncMock(return_value=mock_resp)
        with patch("pawgrab.engine.sitemap.AsyncSession", return_value=mock_session):
            urls, source = await discover_urls("https://example.com")
        assert source == "sitemap"
        assert "https://example.com/page1" in urls
        assert "https://example.com/page2" in urls

    async def test_falls_back_to_homepage(self):
        from pawgrab.engine.sitemap import discover_urls

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        sitemap_resp = MagicMock(status_code=404)
        homepage_resp = MagicMock(
            status_code=200,
            text="""<html><body>
  <a href="/about">About</a>
  <a href="https://example.com/blog">Blog</a>
  <a href="https://other.com/link">External</a>
</body></html>""",
        )
        mock_session.get = AsyncMock(side_effect=[sitemap_resp, sitemap_resp, sitemap_resp, homepage_resp])
        with patch("pawgrab.engine.sitemap.AsyncSession", return_value=mock_session):
            urls, source = await discover_urls("https://example.com")
        assert source == "crawl"
        assert any("example.com" in u for u in urls)
        assert not any("other.com" in u for u in urls)

    async def test_filters_subdomains(self):
        from pawgrab.engine.sitemap import discover_urls

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_resp = MagicMock(
            status_code=200,
            text="""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/page</loc></url>
  <url><loc>https://sub.example.com/other</loc></url>
</urlset>""",
        )
        mock_session.get = AsyncMock(return_value=mock_resp)
        with patch("pawgrab.engine.sitemap.AsyncSession", return_value=mock_session):
            urls, _ = await discover_urls("https://example.com", include_subdomains=False)
        assert "https://example.com/page" in urls
        assert "https://sub.example.com/other" not in urls


class TestSitemapIndexRecursion:
    def test_parse_distinguishes_index_from_urlset(self):
        from pawgrab.engine.sitemap import _parse_sitemap

        index = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>https://example.com/sm1.xml</loc></sitemap>
          <sitemap><loc>https://example.com/sm2.xml</loc></sitemap>
        </sitemapindex>"""
        kind, locs = _parse_sitemap(index)
        assert kind == "index"
        assert locs == ["https://example.com/sm1.xml", "https://example.com/sm2.xml"]
        urlset = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://example.com/a</loc></url>
        </urlset>"""
        kind, locs = _parse_sitemap(urlset)
        assert kind == "urlset"
        assert locs == ["https://example.com/a"]

    def test_doctype_rejected(self):
        from pawgrab.engine.sitemap import _parse_sitemap

        evil = '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]><urlset><url><loc>x</loc></url></urlset>'
        kind, locs = _parse_sitemap(evil)
        assert locs == []

    async def test_index_recursion_yields_page_urls(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from pawgrab.engine.sitemap import discover_urls

        index_xml = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>https://example.com/child.xml</loc></sitemap>
        </sitemapindex>"""
        child_xml = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://example.com/real-page-1</loc></url>
          <url><loc>https://example.com/real-page-2</loc></url>
        </urlset>"""
        responses = {
            "https://example.com/sitemap.xml": index_xml,
            "https://example.com/child.xml": child_xml,
        }
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        async def fake_get(url, **kwargs):
            body = responses.get(url)
            return MagicMock(status_code=200 if body else 404, text=body or "")

        mock_session.get = fake_get
        with patch("pawgrab.engine.sitemap.AsyncSession", return_value=mock_session):
            urls, source = await discover_urls("https://example.com")
        assert source == "sitemap"

        assert "https://example.com/real-page-1" in urls
        assert "https://example.com/real-page-2" in urls
        assert "https://example.com/child.xml" not in urls
