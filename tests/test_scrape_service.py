"""Tests for the shared scrape service."""

from unittest.mock import AsyncMock, patch

import pytest

from pawgrab.engine.fetcher import FetchResult
from pawgrab.engine.scrape_service import scrape_url
from pawgrab.models.common import OutputFormat


@pytest.mark.asyncio
async def test_scrape_url_returns_markdown():
    mock_result = FetchResult(
        html="<html><body><h1>Hello</h1><p>World</p></body></html>",
        status_code=200,
        url="https://example.com",
    )
    with patch("pawgrab.engine.scrape_service.is_allowed", new_callable=AsyncMock, return_value=True):
        with patch("pawgrab.engine.scrape_service.wait_for_slot", new_callable=AsyncMock):
            with patch("pawgrab.engine.scrape_service.fetch_page", new_callable=AsyncMock, return_value=mock_result):
                resp = await scrape_url("https://example.com", formats=[OutputFormat.MARKDOWN])

    assert resp.success is True
    assert resp.url == "https://example.com"


@pytest.mark.asyncio
async def test_scrape_url_blocked_by_robots():
    with patch("pawgrab.engine.scrape_service.is_allowed", new_callable=AsyncMock, return_value=False):
        with pytest.raises(PermissionError):
            await scrape_url("https://example.com")


@pytest.mark.asyncio
async def test_scrape_url_includes_metadata():
    mock_result = FetchResult(
        html="<html><head><title>Test</title></head><body><p>Content</p></body></html>",
        status_code=200,
        url="https://example.com",
    )
    with patch("pawgrab.engine.scrape_service.is_allowed", new_callable=AsyncMock, return_value=True):
        with patch("pawgrab.engine.scrape_service.wait_for_slot", new_callable=AsyncMock):
            with patch("pawgrab.engine.scrape_service.fetch_page", new_callable=AsyncMock, return_value=mock_result):
                resp = await scrape_url(
                    "https://example.com",
                    formats=[OutputFormat.TEXT],
                    include_metadata=True,
                )

    assert resp.metadata is not None
    assert resp.metadata.status_code == 200
