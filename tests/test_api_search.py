"""Tests for the /v1/search endpoint."""

from unittest.mock import AsyncMock, patch

import pytest

from pawgrab.models.scrape import ScrapeResponse


async def test_search_missing_query(client):
    resp = await client.post("/v1/search", json={})
    assert resp.status_code == 422


async def test_search_empty_results(client):
    with patch("pawgrab.api.search.search_web", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = []
        resp = await client.post("/v1/search", json={"query": "test query"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["total"] == 0
    assert data["results"] == []


async def test_search_with_results(client):
    mock_response = ScrapeResponse(
        success=True,
        url="https://example.com",
        markdown="# Example",
    )

    with (
        patch("pawgrab.api.search.search_web", new_callable=AsyncMock) as mock_search,
        patch("pawgrab.api.search.scrape_url", new_callable=AsyncMock) as mock_scrape,
        patch("pawgrab.api.search.get_browser_pool", new_callable=AsyncMock) as mock_pool,
    ):
        mock_search.return_value = ["https://example.com"]
        mock_scrape.return_value = mock_response
        mock_pool.side_effect = Exception("no browser")

        resp = await client.post("/v1/search", json={
            "query": "test query",
            "num_results": 3,
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["total"] == 1
    assert data["query"] == "test query"
    assert data["results"][0]["url"] == "https://example.com"


async def test_search_scrape_failure_partial(client):
    """If one URL fails to scrape, others still succeed."""
    mock_response = ScrapeResponse(
        success=True,
        url="https://good.com",
        markdown="# Good",
    )

    call_count = 0

    async def mock_scrape_fn(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if "bad" in url:
            raise Exception("scrape failed")
        return mock_response

    with (
        patch("pawgrab.api.search.search_web", new_callable=AsyncMock) as mock_search,
        patch("pawgrab.api.search.scrape_url", side_effect=mock_scrape_fn),
        patch("pawgrab.api.search.get_browser_pool", new_callable=AsyncMock) as mock_pool,
    ):
        mock_search.return_value = ["https://bad.com", "https://good.com"]
        mock_pool.side_effect = Exception("no browser")

        resp = await client.post("/v1/search", json={"query": "test"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1  # only the good one
    assert data["results"][0]["url"] == "https://good.com"


async def test_search_provider_error(client):
    with patch("pawgrab.api.search.search_web", new_callable=AsyncMock) as mock_search:
        mock_search.side_effect = Exception("provider down")
        resp = await client.post("/v1/search", json={"query": "test"})
    assert resp.status_code == 502


async def test_search_query_too_long(client):
    resp = await client.post("/v1/search", json={"query": "x" * 501})
    assert resp.status_code == 422
