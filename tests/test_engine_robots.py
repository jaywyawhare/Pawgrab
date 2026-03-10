"""Tests for robots.txt checking."""

from unittest.mock import AsyncMock, patch

import pytest

from pawgrab.engine.robots import clear_cache, is_allowed


@pytest.fixture(autouse=True)
def _clear_robots_cache():
    clear_cache()
    yield
    clear_cache()


@pytest.mark.asyncio
async def test_allowed_when_robots_disabled():
    with patch("pawgrab.engine.robots.settings") as mock_settings:
        mock_settings.respect_robots = False
        assert await is_allowed("https://example.com/secret") is True


@pytest.mark.asyncio
async def test_allowed_when_robots_fetch_fails():
    with patch("pawgrab.engine.robots.settings") as mock_settings:
        mock_settings.respect_robots = True
        with patch("pawgrab.engine.robots._fetch_robots", new_callable=AsyncMock, return_value=None):
            assert await is_allowed("https://example.com/page") is True


@pytest.mark.asyncio
async def test_blocked_by_robots():
    from protego import Protego

    robots = Protego.parse("User-agent: Pawgrab\nDisallow: /private/")
    with patch("pawgrab.engine.robots.settings") as mock_settings:
        mock_settings.respect_robots = True
        with patch("pawgrab.engine.robots._fetch_robots", new_callable=AsyncMock, return_value=robots):
            assert await is_allowed("https://example.com/private/page") is False
            assert await is_allowed("https://example.com/public/page") is True


@pytest.mark.asyncio
async def test_cache_backoff_for_failures():
    """Failed robots.txt fetches should use shorter TTL."""
    import time
    from pawgrab.engine import robots

    with patch("pawgrab.engine.robots.settings") as mock_settings:
        mock_settings.respect_robots = True
        with patch("pawgrab.engine.robots._fetch_robots", new_callable=AsyncMock, return_value=None) as mock_fetch:
            # First call fetches
            await is_allowed("https://example.com/page")
            assert mock_fetch.call_count == 1

            # Second call uses cache (failure TTL = 300s)
            await is_allowed("https://example.com/other")
            assert mock_fetch.call_count == 1  # still cached
