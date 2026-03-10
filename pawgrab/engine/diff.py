"""Content diff engine for change tracking."""

from __future__ import annotations

import difflib
import hashlib

import structlog

from pawgrab.config import settings
from pawgrab.models.monitor import ChangeType, ContentDiff

logger = structlog.get_logger()


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _word_count(text: str) -> int:
    return len(text.split())


def _diff_summary(old: str, new: str, max_lines: int = 20) -> str:
    """Generate a unified diff summary."""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(old_lines, new_lines, lineterm="")
    lines = list(diff)[:max_lines]
    if not lines:
        return ""
    return "".join(lines)


def compare_content(url: str, current_text: str) -> ContentDiff:
    """Compare current content against stored previous version.

    Looks up the in-memory cache; call store_content (async) separately
    to persist snapshots to Redis.
    """
    current_hash = _content_hash(current_text)
    current_wc = _word_count(current_text)

    # Try to load previous content from in-memory cache
    prev = _content_cache.get(url)

    if prev is None:
        return ContentDiff(
            change_type=ChangeType.ADDED,
            current_hash=current_hash,
            current_word_count=current_wc,
        )

    prev_hash = prev["hash"]
    prev_wc = prev["word_count"]
    prev_text = prev["text"]

    if prev_hash == current_hash:
        return ContentDiff(
            change_type=ChangeType.UNCHANGED,
            previous_hash=prev_hash,
            current_hash=current_hash,
            previous_word_count=prev_wc,
            current_word_count=current_wc,
        )

    summary = _diff_summary(prev_text, current_text)
    return ContentDiff(
        change_type=ChangeType.MODIFIED,
        previous_hash=prev_hash,
        current_hash=current_hash,
        previous_word_count=prev_wc,
        current_word_count=current_wc,
        diff_summary=summary,
    )


# In-memory cache + Redis persistence for content snapshots
_content_cache: dict[str, dict] = {}


async def store_content(url: str, text: str, *, ttl: int | None = None) -> None:
    """Store content snapshot for future comparison."""
    content_hash = _content_hash(text)
    wc = _word_count(text)

    # Store in memory
    _content_cache[url] = {
        "hash": content_hash,
        "word_count": wc,
        "text": text,
    }

    # Also persist to Redis for cross-process durability
    try:
        from pawgrab.queue.manager import get_redis

        redis = await get_redis()
        import json

        key = f"pawgrab:monitor:{hashlib.sha256(url.encode()).hexdigest()[:16]}"
        await redis.set(
            key,
            json.dumps({"hash": content_hash, "word_count": wc, "text": text}),
            ex=ttl or settings.monitor_ttl,
        )
    except Exception as exc:
        logger.debug("monitor_redis_store_failed", url=url, error=str(exc))


async def load_content(url: str) -> dict | None:
    """Load previously stored content from Redis (populates cache)."""
    if url in _content_cache:
        return _content_cache[url]

    try:
        from pawgrab.queue.manager import get_redis

        redis = await get_redis()
        import json

        key = f"pawgrab:monitor:{hashlib.sha256(url.encode()).hexdigest()[:16]}"
        raw = await redis.get(key)
        if raw:
            data = json.loads(raw)
            _content_cache[url] = data
            return data
    except Exception as exc:
        logger.debug("monitor_redis_load_failed", url=url, error=str(exc))

    return None
