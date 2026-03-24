"""Tests for the /v1/map endpoint."""

from unittest.mock import AsyncMock, patch

from pawgrab.engine.sitemap import _parse_sitemap_xml


async def test_map_missing_url(client):
    resp = await client.post("/v1/map", json={})
    assert resp.status_code == 422


async def test_map_success(client):
    with patch("pawgrab.api.map.discover_urls", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = (
            ["https://example.com/page1", "https://example.com/page2"],
            "sitemap",
        )
        resp = await client.post("/v1/map", json={"url": "https://example.com"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["total"] == 2
    assert data["source"] == "sitemap"
    assert len(data["urls"]) == 2


async def test_map_crawl_fallback(client):
    with patch("pawgrab.api.map.discover_urls", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = (["https://example.com/about"], "crawl")
        resp = await client.post("/v1/map", json={"url": "https://example.com"})

    data = resp.json()
    assert data["source"] == "crawl"


def test_parse_sitemap_xml_basic():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url><loc>https://example.com/page1</loc></url>
        <url><loc>https://example.com/page2</loc></url>
    </urlset>"""
    urls = _parse_sitemap_xml(xml)
    assert urls == ["https://example.com/page1", "https://example.com/page2"]


def test_parse_sitemap_xml_index():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <sitemap><loc>https://example.com/sitemap1.xml</loc></sitemap>
        <sitemap><loc>https://example.com/sitemap2.xml</loc></sitemap>
    </sitemapindex>"""
    urls = _parse_sitemap_xml(xml)
    assert "https://example.com/sitemap1.xml" in urls
    assert "https://example.com/sitemap2.xml" in urls


def test_parse_sitemap_xml_invalid():
    urls = _parse_sitemap_xml("not xml at all")
    assert urls == []


def test_parse_sitemap_xml_limit():
    entries = "\n".join(f"<url><loc>https://example.com/p{i}</loc></url>" for i in range(100))
    xml = f"""<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        {entries}
    </urlset>"""
    urls = _parse_sitemap_xml(xml, limit=10)
    assert len(urls) == 10


async def test_map_error_handling(client):
    with patch("pawgrab.api.map.discover_urls", new_callable=AsyncMock) as mock_discover:
        mock_discover.side_effect = Exception("connection failed")
        resp = await client.post("/v1/map", json={"url": "https://example.com"})
    assert resp.status_code == 502
