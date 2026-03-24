"""Tests for change tracking / content monitoring."""

from unittest.mock import AsyncMock, patch

import pytest

from pawgrab.engine.diff import _content_cache, compare_content, store_content
from pawgrab.models.monitor import ChangeType, ContentDiff


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the content cache between tests."""
    _content_cache.clear()
    yield
    _content_cache.clear()


def test_first_scrape_is_added():
    """First time scraping a URL should report ADDED."""
    diff = compare_content("https://example.com", "Hello World")
    assert diff.change_type == ChangeType.ADDED
    assert diff.previous_hash is None
    assert diff.current_hash
    assert diff.current_word_count == 2


def test_unchanged_content():
    """Same content should report UNCHANGED."""
    url = "https://example.com"
    text = "Hello World"

    # Simulate previous storage
    from pawgrab.engine.diff import _content_hash
    from pawgrab.utils.text import word_count as _word_count

    _content_cache[url] = {
        "hash": _content_hash(text),
        "word_count": _word_count(text),
        "text": text,
    }

    diff = compare_content(url, text)
    assert diff.change_type == ChangeType.UNCHANGED
    assert diff.previous_hash == diff.current_hash


def test_modified_content():
    """Changed content should report MODIFIED with diff summary."""
    url = "https://example.com"
    old_text = "Hello World"
    new_text = "Hello New World"

    from pawgrab.engine.diff import _content_hash
    from pawgrab.utils.text import word_count as _word_count

    _content_cache[url] = {
        "hash": _content_hash(old_text),
        "word_count": _word_count(old_text),
        "text": old_text,
    }

    diff = compare_content(url, new_text)
    assert diff.change_type == ChangeType.MODIFIED
    assert diff.previous_hash != diff.current_hash
    assert diff.previous_word_count == 2
    assert diff.current_word_count == 3
    assert diff.diff_summary is not None
    assert len(diff.diff_summary) > 0


async def test_store_content_populates_cache():
    """store_content should update the in-memory cache."""
    url = "https://store-test.com"

    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock) as mock_redis:
        redis = AsyncMock()
        mock_redis.return_value = redis

        await store_content(url, "test content", ttl=3600)

    assert url in _content_cache
    assert _content_cache[url]["word_count"] == 2


async def test_store_then_compare():
    """Full cycle: store content, then compare returns UNCHANGED."""
    url = "https://cycle-test.com"
    text = "cycle test content"

    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock) as mock_redis:
        redis = AsyncMock()
        mock_redis.return_value = redis
        await store_content(url, text)

    diff = compare_content(url, text)
    assert diff.change_type == ChangeType.UNCHANGED


def test_content_diff_model():
    """ContentDiff model validation."""
    diff = ContentDiff(
        change_type=ChangeType.MODIFIED,
        previous_hash="abc",
        current_hash="def",
        previous_word_count=10,
        current_word_count=15,
        diff_summary="- old\n+ new",
    )
    assert diff.change_type == ChangeType.MODIFIED
    assert diff.previous_word_count == 10


async def test_scrape_request_monitor_fields():
    """ScrapeRequest model accepts monitor fields."""
    from pawgrab.models.scrape import ScrapeRequest

    req = ScrapeRequest(
        url="https://example.com",
        monitor=True,
        monitor_ttl=7200,
    )
    assert req.monitor is True
    assert req.monitor_ttl == 7200
