"""Tests for the /v1/search endpoint."""

from unittest.mock import AsyncMock, patch

from pawgrab.models.scrape import ScrapeResponse


def _envelope(links, suggestions=None, unresponsive=None, page=1):
    return {
        "query": "test",
        "page": page,
        "category": "general",
        "results": [
            {"position": i + 1, "title": "", "link": u, "snippet": "", "type": "general", "thumbnail": "", "engines": ["duckduckgo"], "score": 1.0} for i, u in enumerate(links)
        ],
        "answers": [],
        "infoboxes": [],
        "suggestions": suggestions or [],
        "corrections": [],
        "unresponsive_engines": unresponsive or [],
        "timings": [],
        "number_of_results": len(links),
    }


async def test_search_missing_query(client):
    resp = await client.post("/v1/search", json={})
    assert resp.status_code == 422


async def test_search_empty_results(client):
    with patch("pawgrab.api.search.run_search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = _envelope([], suggestions=["try this"])
        resp = await client.post("/v1/search", json={"query": "test query"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["total"] == 0
    assert data["results"] == []
    # SERP metadata is surfaced even with nothing to scrape.
    assert data["suggestions"] == ["try this"]


async def test_search_with_results(client):
    mock_response = ScrapeResponse(success=True, url="https://example.com", markdown="# Example")

    with (
        patch("pawgrab.api.search.run_search", new_callable=AsyncMock) as mock_search,
        patch("pawgrab.api.search.scrape_url", new_callable=AsyncMock) as mock_scrape,
        patch("pawgrab.dependencies.get_browser_pool", new_callable=AsyncMock) as mock_pool,
    ):
        mock_search.return_value = _envelope(["https://example.com"])
        mock_scrape.return_value = mock_response
        mock_pool.side_effect = Exception("no browser")

        resp = await client.post("/v1/search", json={"query": "test query", "num_results": 3})

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["total"] == 1
    assert data["results"][0]["url"] == "https://example.com"
    assert data["search_results"][0]["link"] == "https://example.com"


async def test_search_scrape_false_returns_serp_only(client):
    """scrape=false returns ranked SERP metadata without fetching pages."""
    with (
        patch("pawgrab.api.search.run_search", new_callable=AsyncMock) as mock_search,
        patch("pawgrab.api.search.scrape_url", new_callable=AsyncMock) as mock_scrape,
    ):
        mock_search.return_value = _envelope(["https://a.com", "https://b.com"], suggestions=["s"])
        resp = await client.post("/v1/search", json={"query": "test", "scrape": False})

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0  # nothing scraped
    assert [r["link"] for r in data["search_results"]] == ["https://a.com", "https://b.com"]
    assert data["suggestions"] == ["s"]
    mock_scrape.assert_not_called()


async def test_search_scrape_failure_partial(client):
    mock_response = ScrapeResponse(success=True, url="https://good.com", markdown="# Good")

    async def mock_scrape_fn(url, **kwargs):
        if "bad" in url:
            raise Exception("scrape failed")
        return mock_response

    with (
        patch("pawgrab.api.search.run_search", new_callable=AsyncMock) as mock_search,
        patch("pawgrab.api.search.scrape_url", side_effect=mock_scrape_fn),
        patch("pawgrab.dependencies.get_browser_pool", new_callable=AsyncMock) as mock_pool,
    ):
        mock_search.return_value = _envelope(["https://bad.com", "https://good.com"])
        mock_pool.side_effect = Exception("no browser")

        resp = await client.post("/v1/search", json={"query": "test"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["results"][0]["url"] == "https://good.com"


async def test_search_provider_error(client):
    with patch("pawgrab.api.search.run_search", new_callable=AsyncMock) as mock_search:
        mock_search.side_effect = Exception("provider down")
        resp = await client.post("/v1/search", json={"query": "test"})
    assert resp.status_code == 502


async def test_search_query_too_long(client):
    resp = await client.post("/v1/search", json={"query": "x" * 501})
    assert resp.status_code == 422


async def test_search_invalid_time_range_rejected(client):
    resp = await client.post("/v1/search", json={"query": "test", "time_range": "decade"})
    assert resp.status_code == 422
