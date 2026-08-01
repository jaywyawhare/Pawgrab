"""Content diff engine for change tracking."""

from __future__ import annotations

import difflib
import hashlib
from collections import OrderedDict

import structlog

from pawgrab.config import settings
from pawgrab.models.monitor import ChangeType, ContentDiff
from pawgrab.utils.text import word_count

logger = structlog.get_logger()


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


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
    current_wc = word_count(current_text)

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


_MAX_CONTENT_CACHE = 1000
_MAX_TEXT_BYTES = 512 * 1024
_content_cache: OrderedDict[str, dict] = OrderedDict()


async def store_content(url: str, text: str, *, ttl: int | None = None) -> None:
    """Store content snapshot for future comparison."""
    content_hash = _content_hash(text)
    wc = word_count(text)

    stored_text = text[:_MAX_TEXT_BYTES] if len(text) > _MAX_TEXT_BYTES else text
    _content_cache[url] = {
        "hash": content_hash,
        "word_count": wc,
        "text": stored_text,
    }
    _content_cache.move_to_end(url)
    while len(_content_cache) > _MAX_CONTENT_CACHE:
        _content_cache.popitem(last=False)

    try:
        from pawgrab.queue.manager import get_redis

        redis = await get_redis()
        import orjson

        key = f"pawgrab:monitor:{hashlib.sha256(url.encode()).hexdigest()[:16]}"
        await redis.set(
            key,
            orjson.dumps({"hash": content_hash, "word_count": wc, "text": text}).decode(),
            ex=ttl or settings.monitor_ttl,
        )
    except Exception as exc:
        logger.debug("monitor_redis_store_failed", url=url, error=str(exc))


async def load_content(url: str) -> dict | None:
    """Load previously stored content from Redis (populates cache)."""
    if url in _content_cache:
        _content_cache.move_to_end(url)
        return _content_cache[url]

    try:
        from pawgrab.queue.manager import get_redis

        redis = await get_redis()
        import orjson

        key = f"pawgrab:monitor:{hashlib.sha256(url.encode()).hexdigest()[:16]}"
        raw = await redis.get(key)
        if raw:
            data = orjson.loads(raw)
            _content_cache[url] = data
            return data
    except Exception as exc:
        logger.debug("monitor_redis_load_failed", url=url, error=str(exc))

    return None


async def compare_screenshots(url: str, current_screenshot: bytes, *, ttl: int | None = None) -> dict | None:
    """Compare current screenshot with previously stored one.

    Returns diff info including whether changes were detected and
    a pixel difference percentage.
    """
    from pawgrab.config import settings

    ttl = ttl or settings.monitor_ttl
    key = f"pawgrab:screenshot:{hashlib.sha256(url.encode()).hexdigest()[:16]}"

    try:
        from pawgrab.queue.manager import get_redis

        redis = await get_redis()
    except Exception:
        return None

    import base64

    previous_b64 = await redis.get(key)

    # Store current screenshot
    current_b64 = base64.b64encode(current_screenshot).decode()
    await redis.set(key, current_b64, ex=ttl)

    if previous_b64 is None:
        return {
            "has_previous": False,
            "changed": False,
            "diff_percentage": 0.0,
            "message": "First screenshot stored — no previous to compare",
        }

    previous_bytes = base64.b64decode(previous_b64)

    # Compare screenshots using pixel-level diff
    diff_pct = _pixel_diff_percentage(previous_bytes, current_screenshot)

    return {
        "has_previous": True,
        "changed": diff_pct > 1.0,  # >1% pixel change = changed
        "diff_percentage": round(diff_pct, 2),
        "previous_screenshot_base64": previous_b64,
        "message": f"{'Changes detected' if diff_pct > 1.0 else 'No significant changes'} ({diff_pct:.1f}% pixels differ)",
    }


def _pixel_diff_percentage(img1_bytes: bytes, img2_bytes: bytes) -> float:
    """Percentage of differing pixels between two PNG images.

    Decodes both PNGs to raw pixel arrays (via pymupdf) and compares pixel-by-
    pixel — comparing the *compressed* streams is meaningless because a one-pixel
    change reflows the whole compressed output. Falls back to a byte compare only
    if decoding is unavailable.
    """
    if img1_bytes == img2_bytes:
        return 0.0

    decoded = _decode_pixels(img1_bytes)
    decoded2 = _decode_pixels(img2_bytes)
    if decoded is not None and decoded2 is not None:
        (w1, h1, n1, s1), (w2, h2, _n2, s2) = decoded, decoded2
        if (w1, h1) != (w2, h2):
            return 100.0  # different dimensions => fully changed
        stride = max(1, n1)
        total = min(len(s1), len(s2)) // stride
        if total == 0:
            return 100.0
        diff = sum(1 for i in range(0, total * stride, stride) if s1[i : i + stride] != s2[i : i + stride])
        return (diff / total) * 100

    # Fallback: rough byte comparison of the compressed streams.
    len_ratio = min(len(img1_bytes), len(img2_bytes)) / max(len(img1_bytes), len(img2_bytes))
    if len_ratio < 0.8:
        return 100.0
    min_len = min(len(img1_bytes), len(img2_bytes))
    diff_count = sum(1 for i in range(0, min_len, 4) if img1_bytes[i : i + 4] != img2_bytes[i : i + 4])
    total_chunks = min_len // 4
    if total_chunks == 0:
        return 100.0
    return (diff_count / total_chunks) * 100


def _decode_pixels(img_bytes: bytes):
    """Decode a PNG to ``(width, height, channels, samples)`` or None on failure."""
    try:
        import fitz  # pymupdf

        pix = fitz.Pixmap(img_bytes)
        return pix.width, pix.height, pix.n, pix.samples
    except Exception:
        return None
