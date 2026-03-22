"""Response caching layer backed by Redis."""

from __future__ import annotations

import hashlib

import orjson
import structlog

logger = structlog.get_logger()

_DEFAULT_TTL = 300  # 5 minutes


def _cache_key(url: str, params: dict) -> str:
    """Generate a deterministic cache key from URL and request params."""
    raw = orjson.dumps({"url": url, **{k: v for k, v in sorted(params.items()) if v is not None}})
    digest = hashlib.sha256(raw).hexdigest()[:16]
    return f"pawgrab:cache:{digest}"


async def get_cached(url: str, params: dict) -> dict | None:
    """Return cached response dict or None."""
    try:
        from pawgrab.queue.manager import get_redis
        redis = await get_redis()
        raw = await redis.get(_cache_key(url, params))
        if raw:
            logger.debug("cache_hit", url=url)
            return orjson.loads(raw)
    except Exception as exc:
        logger.debug("cache_get_failed", error=str(exc))
    return None


async def set_cached(url: str, params: dict, response_dict: dict, ttl: int = _DEFAULT_TTL) -> None:
    """Cache a response dict with TTL."""
    if ttl <= 0:
        return
    try:
        from pawgrab.queue.manager import get_redis
        redis = await get_redis()
        key = _cache_key(url, params)
        await redis.set(key, orjson.dumps(response_dict).decode(), ex=ttl)
        logger.debug("cache_set", url=url, ttl=ttl)
    except Exception as exc:
        logger.debug("cache_set_failed", error=str(exc))
