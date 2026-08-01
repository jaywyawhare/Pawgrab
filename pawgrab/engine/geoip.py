"""Proxy exit-IP geolocation for fingerprint coherence.

CloakBrowser's ``geoip=True`` resolves the proxy's exit IP to a timezone and
locale so the browser's ``Intl`` timezone, ``navigator.language`` and geolocation
all agree with the IP the site actually sees.  The classic residential-proxy tell
is an IP in Sao Paulo behind a browser reporting ``America/New_York`` and
``en-US`` — anti-bot systems flag that mismatch instantly.

We make one HTTP call *through the proxy* to a free geo endpoint (no API key),
then cache the result per proxy for the process lifetime with a TTL.  The lookup
is best-effort: any failure returns ``None`` and the caller keeps its random
profile, so geoip never blocks a fetch.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import structlog

from pawgrab.config import settings

logger = structlog.get_logger()

# ip-api.com is free, keyless, and returns tz + lat/lon + countryCode in one call.
_GEO_ENDPOINT = "http://ip-api.com/json/?fields=status,countryCode,lat,lon,timezone,query"
_CACHE_TTL_S = 3600.0

# Country -> (locale, accept-language) for English-preferring coherence. Falls
# back to the country's own English variant so language still reads as plausible.
_COUNTRY_LOCALE = {
    "US": ("en-US", "en-US,en;q=0.9"),
    "CA": ("en-CA", "en-CA,en;q=0.9,fr-CA;q=0.7"),
    "GB": ("en-GB", "en-GB,en;q=0.9"),
    "IE": ("en-IE", "en-IE,en;q=0.9"),
    "AU": ("en-AU", "en-AU,en;q=0.9"),
    "NZ": ("en-NZ", "en-NZ,en;q=0.9"),
    "DE": ("en-DE", "en-US,en;q=0.9,de;q=0.7"),
    "FR": ("en-FR", "en-US,en;q=0.9,fr;q=0.7"),
    "NL": ("en-NL", "en-US,en;q=0.9,nl;q=0.7"),
    "ES": ("en-ES", "en-US,en;q=0.9,es;q=0.7"),
    "IT": ("en-IT", "en-US,en;q=0.9,it;q=0.7"),
    "BR": ("en-US", "en-US,en;q=0.9,pt-BR;q=0.7"),
    "IN": ("en-IN", "en-IN,en;q=0.9,hi;q=0.7"),
    "JP": ("en-US", "en-US,en;q=0.9,ja;q=0.7"),
    "SG": ("en-SG", "en-SG,en;q=0.9"),
}
_DEFAULT_LOCALE = ("en-US", "en-US,en;q=0.9")


@dataclass(frozen=True, slots=True)
class ProxyGeo:
    """Resolved geolocation for a proxy exit IP."""

    ip: str
    timezone: str
    locale: str
    accept_language: str
    latitude: float
    longitude: float
    country: str


_cache: dict[str, tuple[float, ProxyGeo | None]] = {}
_locks: dict[str, asyncio.Lock] = {}


def _lock_for(proxy_url: str) -> asyncio.Lock:
    lock = _locks.get(proxy_url)
    if lock is None:
        lock = asyncio.Lock()
        _locks[proxy_url] = lock
    return lock


async def resolve_proxy_geo(proxy_url: str | None) -> ProxyGeo | None:
    """Resolve a proxy's exit-IP geolocation, cached per proxy with a TTL.

    Returns ``None`` when geoip coherence is disabled, no proxy is given, or the
    lookup fails — the caller then keeps its randomized profile.
    """
    if not proxy_url or not settings.geoip_coherence:
        return None

    now = time.monotonic()
    cached = _cache.get(proxy_url)
    if cached is not None and (now - cached[0]) < _CACHE_TTL_S:
        return cached[1]

    async with _lock_for(proxy_url):
        cached = _cache.get(proxy_url)
        if cached is not None and (time.monotonic() - cached[0]) < _CACHE_TTL_S:
            return cached[1]
        geo = await _lookup(proxy_url)
        _cache[proxy_url] = (time.monotonic(), geo)
        return geo


async def _lookup(proxy_url: str) -> ProxyGeo | None:
    from curl_cffi.requests import AsyncSession

    timeout = settings.geoip_timeout_seconds
    try:
        async with AsyncSession(proxy=proxy_url, timeout=timeout) as session:
            resp = await session.get(_GEO_ENDPOINT, timeout=timeout)
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception as exc:
        from pawgrab.utils.url_safety import redact_url_creds

        logger.debug("geoip_lookup_failed", proxy=redact_url_creds(proxy_url), error=str(exc))
        return None

    if not isinstance(data, dict) or data.get("status") != "success":
        return None
    timezone = data.get("timezone")
    if not timezone:
        return None

    country = (data.get("countryCode") or "").upper()
    locale, accept_language = _COUNTRY_LOCALE.get(country, _DEFAULT_LOCALE)
    geo = ProxyGeo(
        ip=str(data.get("query", "")),
        timezone=timezone,
        locale=locale,
        accept_language=accept_language,
        latitude=float(data.get("lat", 0.0) or 0.0),
        longitude=float(data.get("lon", 0.0) or 0.0),
        country=country,
    )
    from pawgrab.utils.url_safety import redact_url_creds

    logger.info("geoip_resolved", proxy=redact_url_creds(proxy_url), ip=geo.ip, tz=geo.timezone, country=country)
    return geo


def clear_cache() -> None:
    """Drop all cached geo lookups (used by tests)."""
    _cache.clear()
    _locks.clear()
