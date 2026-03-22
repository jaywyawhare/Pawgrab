"""Robots.txt compliance checking with cache TTL and backoff for failures."""

from __future__ import annotations

import asyncio
import time

import structlog
from curl_cffi.requests import AsyncSession
from protego import Protego

from pawgrab.config import settings

logger = structlog.get_logger()

_USER_AGENT = "Pawgrab"
_FAILURE_TTL = 300
_MAX_CACHE_SIZE = 2000

_cache: dict[str, tuple[Protego | None, float, bool]] = {}
_cache_lock = asyncio.Lock()
_inflight: dict[str, asyncio.Event] = {}


async def is_allowed(url: str) -> bool:
    """Check if URL is allowed by robots.txt. Returns True if robots is disabled."""
    if not settings.respect_robots:
        return True

    from pawgrab.utils.url import get_base_url

    base = get_base_url(url)

    while True:
        now = time.monotonic()
        async with _cache_lock:
            if base in _cache:
                parser, cached_at, was_failure = _cache[base]
                ttl = _FAILURE_TTL if was_failure else settings.robots_cache_ttl
                if now - cached_at < ttl:
                    if parser is None:
                        return True
                    return parser.can_fetch(url, _USER_AGENT)

            if base in _inflight:
                wait_event: asyncio.Event = _inflight[base]
                fetch_event = None
            else:
                fetch_event = asyncio.Event()
                _inflight[base] = fetch_event
                wait_event = None

        if wait_event is not None:
            await wait_event.wait()
            continue

        parser: Protego | None = None
        try:
            parser = await _fetch_robots(base)
            is_failure = parser is None
            now = time.monotonic()
            async with _cache_lock:
                if len(_cache) >= _MAX_CACHE_SIZE:
                    oldest = min(_cache, key=lambda k: _cache[k][1])
                    del _cache[oldest]
                _cache[base] = (parser, now, is_failure)
        finally:
            async with _cache_lock:
                _inflight.pop(base, None)
            fetch_event.set()

        if parser is None:
            return True
        return parser.can_fetch(url, _USER_AGENT)


async def _fetch_robots(base_url: str) -> Protego | None:
    robots_url = f"{base_url}/robots.txt"
    try:
        async with AsyncSession() as session:
            resp = await session.get(
                robots_url, timeout=settings.robots_fetch_timeout, impersonate="safari184"
            )
            if resp.status_code == 200:
                return Protego.parse(resp.text)
    except Exception:
        logger.info("robots_fetch_failed", url=robots_url)
    return None


def clear_cache():
    _cache.clear()
