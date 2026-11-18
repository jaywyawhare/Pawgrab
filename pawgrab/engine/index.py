"""Content index ("Alexandria-lite", F4): a write-through cache of scraped pages.

Every successful scrape / crawl page / agent fetch upserts its markdown here. A
later search can be answered from the index (ranked lexically, reusing
``engine.ranking``) without re-fetching. Unchanged pages are skipped via a content
hash, reusing the same hashing idea as change-tracking (``engine.diff``).

Backed by Redis by default; degrades to a process-local dict when Redis is absent
so it never blocks a scrape (and so tests run without Redis).
"""

from __future__ import annotations

import hashlib
import time
from urllib.parse import urlsplit

import orjson
import structlog

from pawgrab.config import settings
from pawgrab.engine.ranking import rank_documents

logger = structlog.get_logger()

_PREFIX = "pawgrab:index:"
_KEYSET = "pawgrab:index:__keys__"

# Process-local fallback store: {key: entry_dict}. Only used when Redis is down.
_local: dict[str, dict] = {}


def _key(url: str) -> str:
    return _PREFIX + hashlib.sha256(url.encode()).hexdigest()[:24]


def _domain(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


async def _redis():
    try:
        from pawgrab.queue.manager import get_redis

        return await get_redis()
    except Exception:
        return None


async def upsert(url: str, markdown: str, title: str = "") -> bool:
    """Index (or refresh) a page. Returns True if written, False if unchanged/skipped."""
    if not settings.index_enabled or not markdown or not markdown.strip():
        return False
    content_hash = hashlib.sha256(markdown.encode()).hexdigest()[:16]
    entry = {
        "url": url,
        "title": (title or "")[:300],
        "markdown": markdown[:200_000],
        "markdown_hash": content_hash,
        "word_count": len(markdown.split()),
        "fetched_at": int(time.time()),
        "domain": _domain(url),
    }
    key = _key(url)
    redis = await _redis()
    if redis is None:
        prev = _local.get(key)
        if prev and prev.get("markdown_hash") == content_hash:
            return False
        if len(_local) >= settings.index_max_entries and key not in _local:
            _local.pop(next(iter(_local)), None)
        _local[key] = entry
        return True

    try:
        prev_hash = await redis.hget(key, "markdown_hash")
        if prev_hash == content_hash:
            await redis.expire(key, settings.index_ttl or 0) if settings.index_ttl else None
            return False
        await redis.hset(key, mapping={k: (orjson.dumps(v).decode() if isinstance(v, (dict, list)) else str(v)) for k, v in entry.items()})
        if settings.index_ttl:
            await redis.expire(key, settings.index_ttl)
        await redis.sadd(_KEYSET, key)
        return True
    except Exception as exc:
        logger.warning("index_upsert_failed", url=url, error=str(exc))
        return False


async def _all_entries() -> list[dict]:
    redis = await _redis()
    if redis is None:
        return list(_local.values())
    try:
        keys = await redis.smembers(_KEYSET)
        entries: list[dict] = []
        for key in keys:
            data = await redis.hgetall(key)
            if not data:
                await redis.srem(_KEYSET, key)  # expired — prune the pointer
                continue
            entries.append(data)
        return entries
    except Exception as exc:
        logger.warning("index_scan_failed", error=str(exc))
        return []


async def search(query: str, k: int = 10, include_content: bool = False) -> list[dict]:
    """Return up to k cached entries ranked by lexical relevance to the query."""
    entries = await _all_entries()
    if not entries:
        return []
    ranked = rank_documents(query, entries, text_key="markdown", id_key="url")
    hits: list[dict] = []
    for entry, score in ranked[:k]:
        if score <= 0:
            continue
        hit = {
            "url": entry.get("url", ""),
            "title": entry.get("title", ""),
            "word_count": int(entry.get("word_count", 0) or 0),
            "fetched_at": int(entry.get("fetched_at", 0) or 0),
            "markdown_hash": entry.get("markdown_hash", ""),
            "score": round(float(score), 4),
        }
        if include_content:
            hit["markdown"] = entry.get("markdown", "")
        hits.append(hit)
    return hits


async def get(url: str) -> dict | None:
    """Return a single cached entry by URL, or None."""
    key = _key(url)
    redis = await _redis()
    if redis is None:
        return _local.get(key)
    try:
        data = await redis.hgetall(key)
        return data or None
    except Exception:
        return None


async def stats() -> dict:
    redis = await _redis()
    store = "redis"
    if redis is None:
        return {"enabled": settings.index_enabled, "entries": len(_local), "store": "memory"}
    try:
        count = await redis.scard(_KEYSET)
    except Exception:
        count = 0
    return {"enabled": settings.index_enabled, "entries": int(count or 0), "store": store}


async def delete_domain(domain: str) -> int:
    """Drop every indexed entry for a domain. Returns the number removed."""
    domain = domain.lower().removeprefix("www.")
    entries = await _all_entries()
    removed = 0
    redis = await _redis()
    for entry in entries:
        if entry.get("domain") == domain or _domain(entry.get("url", "")) == domain:
            key = _key(entry.get("url", ""))
            if redis is None:
                _local.pop(key, None)
            else:
                try:
                    await redis.delete(key)
                    await redis.srem(_KEYSET, key)
                except Exception:
                    continue
            removed += 1
    return removed
