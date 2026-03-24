"""Tests for API key authentication middleware."""

import pytest


@pytest.fixture
def auth_app():
    """Create a fresh app with API key configured."""
    from unittest.mock import patch
    with patch("pawgrab.config.settings") as mock_settings:
        mock_settings.api_key = "test-secret-key"
        mock_settings.log_level = "debug"
        mock_settings.redis_url = "redis://localhost:6379/0"
        mock_settings.openai_api_key = ""
        mock_settings.openai_model = "gpt-4o-mini"
        mock_settings.browser_pool_size = 1
        mock_settings.rate_limit_rpm = 60
        mock_settings.respect_robots = True
        mock_settings.stealth_mode = True
        mock_settings.max_challenge_retries = 2
        mock_settings.impersonate = ""
        mock_settings.proxy_url = ""
        mock_settings.max_timeout = 120000

        # Reimport to pick up patched settings
        import importlib

        import pawgrab.main
        importlib.reload(pawgrab.main)
        yield pawgrab.main.app


async def test_health_exempt_from_auth(client):
    """Health endpoints should not require auth even when API key is set."""
    resp = await client.get("/health")
    assert resp.status_code == 200


async def test_status_exempt_from_auth(client):
    resp = await client.get("/status")
    assert resp.status_code == 200


async def test_scrape_without_auth_key_passes(client):
    """When no API key is configured, requests should pass through."""
    # This uses the default app which has no API key
    resp = await client.post("/v1/scrape", json={"url": "not-valid"})
    # Should get 422 (validation error), NOT 401
    assert resp.status_code == 422
