from unittest.mock import AsyncMock, patch

import pytest

from pawgrab.engine.diff import (
    _content_hash,
    _diff_summary,
    _pixel_diff_percentage,
    compare_content,
    store_content,
)
from pawgrab.models.monitor import ChangeType


class TestContentHash:
    def test_deterministic(self):
        assert _content_hash("hello") == _content_hash("hello")

    def test_different_texts_differ(self):
        assert _content_hash("hello") != _content_hash("world")

    def test_returns_sha256_hex(self):
        h = _content_hash("test")
        assert len(h) == 64
        int(h, 16)


class TestDiffSummary:
    def test_identical_texts_empty(self):
        assert _diff_summary("hello", "hello") == ""

    def test_changed_text(self):
        diff = _diff_summary("line1\nline2\n", "line1\nline3\n")
        assert "-line2" in diff
        assert "+line3" in diff

    def test_max_lines_limit(self):
        old = "\n".join([f"line{i}" for i in range(100)])
        diff = _diff_summary(old, old + "\nnewline", max_lines=5)
        assert len(diff.splitlines()) <= 5


class TestCompareContent:
    def setup_method(self):
        from pawgrab.engine.diff import _content_cache

        _content_cache.clear()

    def test_first_comparison_is_added(self):
        result = compare_content("https://example.com", "some content")
        assert result.change_type == ChangeType.ADDED
        assert result.previous_hash is None

    def test_unchanged_content(self):
        url = "https://example.com/page"
        text = "static content"
        from pawgrab.engine.diff import _content_cache

        _content_cache[url] = {"hash": _content_hash(text), "word_count": 2, "text": text}

        result = compare_content(url, text)
        assert result.change_type == ChangeType.UNCHANGED
        assert result.previous_hash == result.current_hash

    def test_modified_content(self):
        url = "https://example.com/modified"
        old_text = "old content here"
        new_text = "new content here"
        from pawgrab.engine.diff import _content_cache

        _content_cache[url] = {"hash": _content_hash(old_text), "word_count": 3, "text": old_text}

        result = compare_content(url, new_text)
        assert result.change_type == ChangeType.MODIFIED
        assert result.previous_hash != result.current_hash
        assert result.diff_summary is not None

    def test_word_counts_populated(self):
        url = "https://example.com/wc"
        old_text = "one two three"
        new_text = "one two three four"
        from pawgrab.engine.diff import _content_cache

        _content_cache[url] = {"hash": _content_hash(old_text), "word_count": 3, "text": old_text}

        result = compare_content(url, new_text)
        assert result.previous_word_count == 3
        assert result.current_word_count == 4


@pytest.mark.asyncio
class TestStoreContent:
    def setup_method(self):
        from pawgrab.engine.diff import _content_cache

        _content_cache.clear()

    async def test_stores_to_in_memory_cache(self):
        url = "https://example.com/store"
        text = "content to store"
        with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, side_effect=Exception("no redis")):
            await store_content(url, text)

        from pawgrab.engine.diff import _content_cache

        assert url in _content_cache
        assert _content_cache[url]["hash"] == _content_hash(text)

    async def test_lru_eviction_at_max(self):
        from pawgrab.engine.diff import _MAX_CONTENT_CACHE, _content_cache

        for i in range(_MAX_CONTENT_CACHE + 5):
            with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, side_effect=Exception("no redis")):
                await store_content(f"https://example.com/{i}", f"content {i}")
        assert len(_content_cache) <= _MAX_CONTENT_CACHE

    async def test_stores_to_redis_when_available(self):
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            await store_content("https://example.com/redis", "redis content")
        mock_redis.set.assert_called_once()


class TestPixelDiff:
    def test_identical_images(self):
        data = bytes(range(256)) * 4
        assert _pixel_diff_percentage(data, data) == 0.0

    def test_different_sizes(self):
        assert _pixel_diff_percentage(bytes(100), bytes(1000)) == 100.0

    def test_partial_diff(self):
        img1 = bytes([0, 0, 0, 0] * 100)
        img2 = bytes([255, 255, 255, 255] * 50 + [0, 0, 0, 0] * 50)
        pct = _pixel_diff_percentage(img1, img2)
        assert 0 < pct <= 100

    def test_empty_images(self):
        assert _pixel_diff_percentage(b"", b"") == 0.0
