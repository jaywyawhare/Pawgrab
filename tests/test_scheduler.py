import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pawgrab.engine.scheduler import (
    _deserialize_schedule,
    _next_cron_time,
    create_schedule,
    delete_schedule,
    get_due_schedules,
    get_schedule,
    list_schedules,
    update_schedule_run,
)


class TestDeserializeSchedule:
    def _base_data(self, **overrides):
        data = {
            "schedule_id": "abc123",
            "url": "https://example.com",
            "cron": "0 * * * *",
            "max_pages": "10",
            "max_depth": "3",
            "formats": '["markdown"]',
            "webhook_url": "",
            "strategy": "bfs",
            "created_at": "1700000000",
            "last_run": "0",
            "next_run": "1700003600",
            "run_count": "5",
            "enabled": "1",
        }
        data.update(overrides)
        return data

    def test_basic_deserialization(self):
        result = _deserialize_schedule(self._base_data())
        assert result["schedule_id"] == "abc123"
        assert result["url"] == "https://example.com"
        assert result["max_pages"] == 10
        assert result["max_depth"] == 3
        assert result["formats"] == ["markdown"]
        assert result["run_count"] == 5
        assert result["enabled"] is True

    def test_disabled_schedule(self):
        result = _deserialize_schedule(self._base_data(enabled="0"))
        assert result["enabled"] is False

    def test_empty_webhook_url_becomes_none(self):
        result = _deserialize_schedule(self._base_data(webhook_url=""))
        assert result["webhook_url"] is None


class TestNextCronTime:
    def test_valid_cron_returns_future_timestamp(self):
        assert _next_cron_time("0 * * * *") > time.time()

    def test_invalid_cron_falls_back_to_1h(self):
        now = time.time()
        ts = _next_cron_time("not-a-cron")
        assert abs(ts - (now + 3600)) < 5


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.hset = AsyncMock()
    redis.sadd = AsyncMock()
    redis.hgetall = AsyncMock()
    redis.smembers = AsyncMock()
    redis.delete = AsyncMock()
    redis.srem = AsyncMock()
    redis.hincrby = AsyncMock()
    pipeline = AsyncMock()
    pipeline.__aenter__ = AsyncMock(return_value=pipeline)
    pipeline.__aexit__ = AsyncMock(return_value=False)
    pipeline.hgetall = AsyncMock()
    pipeline.execute = AsyncMock()
    redis.pipeline = MagicMock(return_value=pipeline)
    return redis


async def test_create_schedule(mock_redis):
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=mock_redis):
        schedule_id = await create_schedule(
            url="https://example.com",
            cron="0 * * * *",
            max_pages=5,
            max_depth=2,
            formats=["markdown"],
        )
    assert isinstance(schedule_id, str)
    assert len(schedule_id) == 12
    mock_redis.hset.assert_called_once()
    mock_redis.sadd.assert_called_once()


async def test_get_schedule_found(mock_redis):
    mock_redis.hgetall.return_value = {
        "schedule_id": "abc123456789",
        "url": "https://example.com",
        "cron": "0 * * * *",
        "max_pages": "10",
        "max_depth": "3",
        "formats": '["markdown"]',
        "webhook_url": "",
        "strategy": "bfs",
        "created_at": "1700000000",
        "last_run": "0",
        "next_run": "1700003600",
        "run_count": "0",
        "enabled": "1",
    }
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=mock_redis):
        result = await get_schedule("abc123456789")
    assert result is not None
    assert result["schedule_id"] == "abc123456789"


async def test_get_schedule_not_found(mock_redis):
    mock_redis.hgetall.return_value = {}
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=mock_redis):
        assert await get_schedule("nonexistent") is None


async def test_list_schedules_empty(mock_redis):
    mock_redis.smembers.return_value = set()
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=mock_redis):
        assert await list_schedules() == []


async def test_list_schedules_multiple(mock_redis):
    mock_redis.smembers.return_value = {"id1", "id2"}
    schedule_data = {
        "schedule_id": "id1",
        "url": "https://example.com",
        "cron": "0 * * * *",
        "max_pages": "10",
        "max_depth": "3",
        "formats": '["markdown"]',
        "webhook_url": "",
        "strategy": "bfs",
        "created_at": "1700000000",
        "last_run": "0",
        "next_run": "1700003600",
        "run_count": "0",
        "enabled": "1",
    }
    mock_redis.pipeline.return_value.execute = AsyncMock(return_value=[schedule_data, schedule_data])
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=mock_redis):
        assert len(await list_schedules()) == 2


async def test_delete_schedule_success(mock_redis):
    mock_redis.delete.return_value = 1
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=mock_redis):
        assert await delete_schedule("abc123") is True
    mock_redis.srem.assert_called_once()


async def test_delete_schedule_not_found(mock_redis):
    mock_redis.delete.return_value = 0
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=mock_redis):
        assert await delete_schedule("nonexistent") is False


async def test_update_schedule_run(mock_redis):
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=mock_redis):
        await update_schedule_run("abc123", "0 * * * *")
    mock_redis.hset.assert_called_once()
    mock_redis.hincrby.assert_called_once()


async def test_get_due_schedules():
    now = int(time.time())
    schedules = [
        {"enabled": True, "next_run": now - 10, "schedule_id": "due1"},
        {"enabled": True, "next_run": now + 3600, "schedule_id": "future"},
        {"enabled": False, "next_run": now - 10, "schedule_id": "disabled"},
    ]
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)  # lease claim succeeds
    with (
        patch("pawgrab.engine.scheduler.list_schedules", new_callable=AsyncMock, return_value=schedules),
        patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=mock_redis),
    ):
        due = await get_due_schedules()
    assert len(due) == 1
    assert due[0]["schedule_id"] == "due1"
    # The due schedule was atomically claimed (SET NX).
    mock_redis.set.assert_awaited_once()


async def test_get_due_schedules_skips_already_claimed():
    now = int(time.time())
    schedules = [{"enabled": True, "next_run": now - 10, "schedule_id": "due1"}]
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=None)  # lease already held elsewhere
    with (
        patch("pawgrab.engine.scheduler.list_schedules", new_callable=AsyncMock, return_value=schedules),
        patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=mock_redis),
    ):
        due = await get_due_schedules()
    assert due == []


async def test_create_schedule_rejects_invalid_cron():
    import pytest

    from pawgrab.engine.scheduler import create_schedule

    with pytest.raises(ValueError):
        await create_schedule(url="https://example.com", cron="not a cron")
