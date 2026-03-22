"""Cron-based scheduled crawl support."""

from __future__ import annotations

import time
import uuid

import orjson
import structlog

logger = structlog.get_logger()

_SCHEDULE_PREFIX = "pawgrab:schedule:"
_SCHEDULES_SET = "pawgrab:schedules"


def _deserialize_schedule(data: dict) -> dict:
    """Convert a raw Redis hash dict into a typed schedule dict."""
    return {
        "schedule_id": data["schedule_id"],
        "url": data["url"],
        "cron": data["cron"],
        "max_pages": int(data.get("max_pages", 10)),
        "max_depth": int(data.get("max_depth", 3)),
        "formats": orjson.loads(data.get("formats", '["markdown"]')),
        "webhook_url": data.get("webhook_url") or None,
        "strategy": data.get("strategy", "bfs"),
        "created_at": int(data.get("created_at", 0)),
        "last_run": int(data.get("last_run", 0)),
        "next_run": int(data.get("next_run", 0)),
        "run_count": int(data.get("run_count", 0)),
        "enabled": data.get("enabled") == "1",
    }


async def create_schedule(
    *,
    url: str,
    cron: str,
    max_pages: int = 10,
    max_depth: int = 3,
    formats: list[str] | None = None,
    webhook_url: str | None = None,
    strategy: str = "bfs",
) -> str:
    """Create a scheduled crawl. Returns schedule ID."""
    from pawgrab.queue.manager import get_redis
    schedule_id = uuid.uuid4().hex[:12]
    redis = await get_redis()
    data = {
        "schedule_id": schedule_id,
        "url": url,
        "cron": cron,
        "max_pages": str(max_pages),
        "max_depth": str(max_depth),
        "formats": orjson.dumps(formats or ["markdown"]).decode(),
        "webhook_url": webhook_url or "",
        "strategy": strategy,
        "created_at": str(int(time.time())),
        "last_run": "0",
        "next_run": str(_next_cron_time(cron)),
        "run_count": "0",
        "enabled": "1",
    }
    key = f"{_SCHEDULE_PREFIX}{schedule_id}"
    await redis.hset(key, mapping=data)
    await redis.sadd(_SCHEDULES_SET, schedule_id)
    logger.info("schedule_created", schedule_id=schedule_id, cron=cron, url=url)
    return schedule_id


async def get_schedule(schedule_id: str) -> dict | None:
    from pawgrab.queue.manager import get_redis
    redis = await get_redis()
    data = await redis.hgetall(f"{_SCHEDULE_PREFIX}{schedule_id}")
    return _deserialize_schedule(data) if data else None


async def list_schedules() -> list[dict]:
    from pawgrab.queue.manager import get_redis
    redis = await get_redis()
    ids = await redis.smembers(_SCHEDULES_SET)
    if not ids:
        return []

    pipe = redis.pipeline()
    for sid in ids:
        pipe.hgetall(f"{_SCHEDULE_PREFIX}{sid}")
    all_data = await pipe.execute()

    result = []
    for data in all_data:
        if not data:
            continue
        try:
            result.append(_deserialize_schedule(data))
        except Exception:
            continue
    return sorted(result, key=lambda s: s["created_at"], reverse=True)


async def delete_schedule(schedule_id: str) -> bool:
    from pawgrab.queue.manager import get_redis
    redis = await get_redis()
    deleted = await redis.delete(f"{_SCHEDULE_PREFIX}{schedule_id}")
    await redis.srem(_SCHEDULES_SET, schedule_id)
    return bool(deleted)


async def update_schedule_run(schedule_id: str, cron: str) -> None:
    """Update last_run and next_run after a scheduled crawl executes."""
    from pawgrab.queue.manager import get_redis
    redis = await get_redis()
    now = int(time.time())
    key = f"{_SCHEDULE_PREFIX}{schedule_id}"
    await redis.hset(key, mapping={
        "last_run": str(now),
        "next_run": str(_next_cron_time(cron)),
    })
    await redis.hincrby(key, "run_count", 1)


def _next_cron_time(cron_expr: str) -> int:
    """Calculate next run time from a cron expression using croniter."""
    try:
        from croniter import croniter
        it = croniter(cron_expr, time.time())
        return int(it.get_next(float))
    except Exception:
        logger.warning("invalid_cron_expression", cron=cron_expr, fallback="1h")
        return int(time.time()) + 3600


async def get_due_schedules() -> list[dict]:
    """Get all schedules that are due to run."""
    now = int(time.time())
    schedules = await list_schedules()
    return [s for s in schedules if s["enabled"] and s["next_run"] <= now]
