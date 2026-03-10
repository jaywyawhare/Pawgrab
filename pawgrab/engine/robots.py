"""Robots.txt compliance checking with cache TTL and backoff for failures."""

from __future__ import annotations

import time

import structlog
from curl_cffi.requests import AsyncSession
from protego import Protego

from pawgrab.config import settings

logger = structlog.get_logger()

_USER_AGENT = "Pawgrab"
_CACHE_TTL = 3600  # 1 hour for successful fetches
_FAILURE_TTL = 300  # 5 minutes backoff for failed fetches

# Cache stores (parser, timestamp, is_failure) tuples
_cache: dict[str, tuple[Protego | None, float, bool]] = {}


async def is_allowed(url: str) -> bool:
    """Check if URL is allowed by robots.txt. Returns True if robots is disabled."""
    if not settings.respect_robots:
        return True

    from pawgrab.utils.url import get_base_url

    base = get_base_url(url)
    now = time.monotonic()

    if base in _cache:
        parser, cached_at, was_failure = _cache[base]
        ttl = _FAILURE_TTL if was_failure else _CACHE_TTL
        if now - cached_at < ttl:
            if parser is None:
                return True
            return parser.can_fetch(url, _USER_AGENT)

    # Cache miss or expired
    parser = await _fetch_robots(base)
    is_failure = parser is None
    _cache[base] = (parser, now, is_failure)

    if parser is None:
        return True
    return parser.can_fetch(url, _USER_AGENT)


async def _fetch_robots(base_url: str) -> Protego | None:
    robots_url = f"{base_url}/robots.txt"
    try:
        async with AsyncSession() as session:
            resp = await session.get(robots_url, timeout=10, impersonate="safari184")
            if resp.status_code == 200:
                return Protego.parse(resp.text)
    except Exception:
        logger.debug("robots_fetch_failed", url=robots_url)
    return None


def clear_cache():
    _cache.clear()
