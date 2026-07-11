"""Tests for proxy exit-IP geolocation coherence."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pawgrab.config import settings
from pawgrab.engine import geoip
from pawgrab.engine.geoip import ProxyGeo, resolve_proxy_geo


@pytest.fixture(autouse=True)
def _clear_cache():
    geoip.clear_cache()
    yield
    geoip.clear_cache()


async def test_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "geoip_coherence", False)
    assert await resolve_proxy_geo("http://proxy:8080") is None


async def test_no_proxy_returns_none():
    assert await resolve_proxy_geo(None) is None
    assert await resolve_proxy_geo("") is None


def _mock_session(payload):
    """Build an AsyncSession context manager whose .get returns *payload*."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value=payload)
    session = MagicMock()
    session.get = AsyncMock(return_value=resp)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


async def test_resolves_timezone_and_locale(monkeypatch):
    monkeypatch.setattr(settings, "geoip_coherence", True)
    payload = {
        "status": "success",
        "countryCode": "GB",
        "lat": 51.5,
        "lon": -0.12,
        "timezone": "Europe/London",
        "query": "1.2.3.4",
    }
    with patch("curl_cffi.requests.AsyncSession", return_value=_mock_session(payload)):
        geo = await resolve_proxy_geo("http://proxy:8080")
    assert isinstance(geo, ProxyGeo)
    assert geo.timezone == "Europe/London"
    assert geo.locale == "en-GB"
    assert geo.accept_language.startswith("en-GB")
    assert geo.ip == "1.2.3.4"
    assert geo.country == "GB"


async def test_brazil_keeps_english_but_offers_portuguese(monkeypatch):
    monkeypatch.setattr(settings, "geoip_coherence", True)
    payload = {
        "status": "success",
        "countryCode": "BR",
        "lat": -23.5,
        "lon": -46.6,
        "timezone": "America/Sao_Paulo",
        "query": "5.6.7.8",
    }
    with patch("curl_cffi.requests.AsyncSession", return_value=_mock_session(payload)):
        geo = await resolve_proxy_geo("http://br-proxy:8080")
    assert geo.timezone == "America/Sao_Paulo"
    assert "pt-BR" in geo.accept_language


async def test_result_is_cached(monkeypatch):
    monkeypatch.setattr(settings, "geoip_coherence", True)
    payload = {
        "status": "success",
        "countryCode": "US",
        "lat": 40.0,
        "lon": -74.0,
        "timezone": "America/New_York",
        "query": "9.9.9.9",
    }
    ctx = _mock_session(payload)
    with patch("curl_cffi.requests.AsyncSession", return_value=ctx) as mk:
        await resolve_proxy_geo("http://cache-proxy:8080")
        await resolve_proxy_geo("http://cache-proxy:8080")
    # Second call served from cache: only one session constructed.
    assert mk.call_count == 1


async def test_failed_status_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "geoip_coherence", True)
    payload = {"status": "fail", "message": "private range"}
    with patch("curl_cffi.requests.AsyncSession", return_value=_mock_session(payload)):
        assert await resolve_proxy_geo("http://bad-proxy:8080") is None


async def test_lookup_exception_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "geoip_coherence", True)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("proxy down"))
    ctx.__aexit__ = AsyncMock(return_value=False)
    with patch("curl_cffi.requests.AsyncSession", return_value=ctx):
        assert await resolve_proxy_geo("http://dead-proxy:8080") is None
