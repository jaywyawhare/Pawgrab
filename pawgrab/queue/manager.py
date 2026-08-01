"""Job management via Redis."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import orjson
import structlog
from redis.asyncio import Redis

from pawgrab.config import settings
from pawgrab.models.batch import BatchJobStatus
from pawgrab.models.crawl import CrawlJobStatus, CrawlStatus
from pawgrab.queue.pool import JOB_ID_RE

logger = structlog.get_logger()

_redis: Redis | None = None
_redis_lock = asyncio.Lock()

_HEARTBEAT_INTERVAL = 15


def _job_ttl() -> int:
    """Status-hash lifetime, refreshed on every update (see config.job_ttl_seconds)."""
    return settings.job_ttl_seconds


async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        async with _redis_lock:
            if _redis is None:
                _redis = Redis.from_url(
                    settings.redis_url,
                    decode_responses=True,
                    socket_timeout=settings.redis_operation_timeout,
                    socket_connect_timeout=settings.redis_operation_timeout,
                )
    return _redis


async def close_redis():
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def _key(prefix: str, job_id: str) -> str:
    return f"pawgrab:{prefix}:{job_id}"


def _results_key(prefix: str, job_id: str) -> str:
    return f"pawgrab:{prefix}:{job_id}:results"


def _jobs_index(prefix: str) -> str:
    return f"pawgrab:{prefix}:index"


async def _create_job(prefix: str, fields: dict[str, Any], *, webhook_url: str | None = None) -> str:
    job_id = uuid.uuid4().hex[:12]
    redis = await get_redis()
    now = int(time.time())
    fields.update(
        {
            "job_id": job_id,
            "status": CrawlStatus.QUEUED.value,
            "error": "",
            "webhook_url": webhook_url or "",
            "created_at": now,
        }
    )
    await redis.hset(_key(prefix, job_id), mapping=fields)
    await redis.expire(_key(prefix, job_id), _job_ttl())
    # Register in a sorted index (by creation time) so jobs can be listed.
    await redis.zadd(_jobs_index(prefix), {job_id: now})
    return job_id


async def _list_jobs(prefix: str, *, page: int = 1, limit: int = 50) -> tuple[list[dict], int]:
    """List jobs for a prefix, newest first, with their status snapshots."""
    redis = await get_redis()
    index = _jobs_index(prefix)
    total = await redis.zcard(index)
    start = (page - 1) * limit
    job_ids = await redis.zrevrange(index, start, start + limit - 1)
    jobs = []
    for jid in job_ids:
        data = await redis.hgetall(_key(prefix, jid))
        if not data:
            # Job hash expired — drop the stale index entry.
            await redis.zrem(index, jid)
            continue
        jobs.append(
            {
                "job_id": jid,
                "status": data.get("status", "unknown"),
                "created_at": int(data.get("created_at", 0) or 0),
                "error": data.get("error") or None,
            }
        )
    return jobs, total


async def _request_cancel(prefix: str, job_id: str) -> bool:
    """Flag a job for cancellation. Returns False if the job doesn't exist."""
    if not JOB_ID_RE.match(job_id):
        return False
    redis = await get_redis()
    key = _key(prefix, job_id)
    if not await redis.exists(key):
        return False
    status = await redis.hget(key, "status")
    if status in (CrawlStatus.COMPLETED.value, CrawlStatus.FAILED.value, CrawlStatus.CANCELLED.value):
        return False
    await redis.hset(key, mapping={"cancel_requested": "1"})
    await redis.expire(key, _job_ttl())
    return True


async def is_cancel_requested(prefix: str, job_id: str) -> bool:
    redis = await get_redis()
    return (await redis.hget(_key(prefix, job_id), "cancel_requested")) == "1"


_DLQ_KEY = "pawgrab:dead_letter"
_DLQ_MAX = 1000


async def record_dead_letter(job_type: str, job_id: str, error: str, *, meta: dict | None = None) -> None:
    """Record a terminally-failed job for inspection/replay (dead-letter queue)."""
    try:
        redis = await get_redis()
        entry = orjson.dumps(
            {
                "job_type": job_type,
                "job_id": job_id,
                "error": error[:2000],
                "ts": int(time.time()),
                "meta": meta or {},
            }
        ).decode()
        await redis.lpush(_DLQ_KEY, entry)
        await redis.ltrim(_DLQ_KEY, 0, _DLQ_MAX - 1)  # keep newest _DLQ_MAX
    except Exception as exc:
        logger.warning("dead_letter_record_failed", job_id=job_id, error=str(exc))


async def get_dead_letters(limit: int = 100) -> list[dict]:
    """Return the most recent dead-lettered jobs."""
    redis = await get_redis()
    raw = await redis.lrange(_DLQ_KEY, 0, max(0, limit - 1))
    out = []
    for r in raw:
        try:
            out.append(orjson.loads(r))
        except orjson.JSONDecodeError:
            continue
    return out


async def _get_job_data(prefix: str, job_id: str, *, page: int = 1, limit: int = 50) -> tuple[dict, list, int] | None:
    if not JOB_ID_RE.match(job_id):
        return None
    redis = await get_redis()
    data = await redis.hgetall(_key(prefix, job_id))
    if not data:
        return None
    start = (page - 1) * limit
    raw = await redis.lrange(_results_key(prefix, job_id), start, start + limit - 1)
    total = await redis.llen(_results_key(prefix, job_id))
    results = []
    for r in raw:
        try:
            results.append(orjson.loads(r))
        except orjson.JSONDecodeError:
            logger.warning("corrupt_result", prefix=prefix, job_id=job_id)
    return data, results, total


async def _update_job(prefix: str, job_id: str, **fields: Any) -> None:
    updates = {k: v.value if hasattr(v, "value") else v for k, v in fields.items() if v is not None}
    if updates:
        redis = await get_redis()
        key = _key(prefix, job_id)
        await redis.hset(key, mapping=updates)
        # Refresh TTL so a long-running job's status never expires mid-run.
        await redis.expire(key, _job_ttl())


async def _append_result(prefix: str, job_id: str, result_dict: dict) -> None:
    redis = await get_redis()
    key = _results_key(prefix, job_id)
    await redis.rpush(key, orjson.dumps(result_dict).decode())
    await redis.expire(key, _job_ttl())


async def _get_webhook_url(prefix: str, job_id: str) -> str | None:
    redis = await get_redis()
    url = await redis.hget(_key(prefix, job_id), "webhook_url")
    return url if url else None


async def create_job(
    url: str,
    max_pages: int,
    max_depth: int,
    formats: list[str],
    *,
    webhook_url: str | None = None,
) -> str:
    return await _create_job(
        "crawl",
        {
            "url": url,
            "max_pages": max_pages,
            "max_depth": max_depth,
            "formats": orjson.dumps(formats).decode(),
            "pages_scraped": 0,
        },
        webhook_url=webhook_url,
    )


async def get_job(job_id: str, *, page: int = 1, limit: int = 50) -> CrawlJobStatus | None:
    row = await _get_job_data("crawl", job_id, page=page, limit=limit)
    if row is None:
        return None
    data, results, total = row
    start = (page - 1) * limit
    return CrawlJobStatus(
        job_id=data["job_id"],
        status=CrawlStatus(data["status"]),
        pages_scraped=int(data.get("pages_scraped", 0)),
        results=results,
        error=data.get("error") or None,
        page=page,
        limit=limit,
        total_results=total,
        has_next=(start + len(results)) < total,
    )


async def update_job(job_id: str, *, status: CrawlStatus | None = None, pages_scraped: int | None = None, error: str | None = None):
    await _update_job("crawl", job_id, status=status, pages_scraped=pages_scraped, error=error)


async def append_result(job_id: str, result_dict: dict):
    await _append_result("crawl", job_id, result_dict)


async def get_webhook_url(job_id: str) -> str | None:
    return await _get_webhook_url("crawl", job_id)


async def list_crawl_jobs(*, page: int = 1, limit: int = 50) -> tuple[list[dict], int]:
    return await _list_jobs("crawl", page=page, limit=limit)


async def cancel_crawl_job(job_id: str) -> bool:
    return await _request_cancel("crawl", job_id)


async def crawl_cancel_requested(job_id: str) -> bool:
    return await is_cancel_requested("crawl", job_id)


async def list_batch_jobs(*, page: int = 1, limit: int = 50) -> tuple[list[dict], int]:
    return await _list_jobs("batch", page=page, limit=limit)


async def cancel_batch_job(job_id: str) -> bool:
    return await _request_cancel("batch", job_id)


async def batch_cancel_requested(job_id: str) -> bool:
    return await is_cancel_requested("batch", job_id)


async def create_batch_job(urls: list[str], formats: list[str], *, webhook_url: str | None = None) -> str:
    return await _create_job(
        "batch",
        {
            "urls": orjson.dumps(urls).decode(),
            "total_urls": len(urls),
            "formats": orjson.dumps(formats).decode(),
            "urls_scraped": 0,
        },
        webhook_url=webhook_url,
    )


async def get_batch_job(job_id: str, *, page: int = 1, limit: int = 50) -> BatchJobStatus | None:
    row = await _get_job_data("batch", job_id, page=page, limit=limit)
    if row is None:
        return None
    data, results, total = row
    start = (page - 1) * limit
    return BatchJobStatus(
        job_id=data["job_id"],
        status=CrawlStatus(data["status"]),
        urls_scraped=int(data.get("urls_scraped", 0)),
        total_urls=int(data.get("total_urls", 0)),
        results=results,
        error=data.get("error") or None,
        page=page,
        limit=limit,
        total_results=total,
        has_next=(start + len(results)) < total,
    )


async def update_batch_job(job_id: str, *, status: CrawlStatus | None = None, urls_scraped: int | None = None, error: str | None = None):
    await _update_job("batch", job_id, status=status, urls_scraped=urls_scraped, error=error)


async def append_batch_result(job_id: str, result_dict: dict):
    await _append_result("batch", job_id, result_dict)


async def get_batch_webhook_url(job_id: str) -> str | None:
    return await _get_webhook_url("batch", job_id)


async def create_batch_extract_job(urls: list[str], strategy: str, *, webhook_url: str | None = None) -> str:
    return await _create_job(
        "batch_extract",
        {
            "urls": orjson.dumps(urls).decode(),
            "total_urls": len(urls),
            "strategy": strategy,
            "urls_extracted": 0,
        },
        webhook_url=webhook_url,
    )


async def get_batch_extract_job(job_id: str, *, page: int = 1, limit: int = 50):
    from pawgrab.models.batch_extract import BatchExtractJobStatus

    row = await _get_job_data("batch_extract", job_id, page=page, limit=limit)
    if row is None:
        return None
    data, results, total = row
    start = (page - 1) * limit
    return BatchExtractJobStatus(
        job_id=data["job_id"],
        status=CrawlStatus(data["status"]),
        urls_extracted=int(data.get("urls_extracted", 0)),
        total_urls=int(data.get("total_urls", 0)),
        results=results,
        error=data.get("error") or None,
        page=page,
        limit=limit,
        total_results=total,
        has_next=(start + len(results)) < total,
    )


async def update_batch_extract_job(job_id: str, *, status: CrawlStatus | None = None, urls_extracted: int | None = None, error: str | None = None):
    await _update_job("batch_extract", job_id, status=status, urls_extracted=urls_extracted, error=error)


async def append_batch_extract_result(job_id: str, result_dict: dict):
    await _append_result("batch_extract", job_id, result_dict)


async def get_batch_extract_webhook_url(job_id: str) -> str | None:
    return await _get_webhook_url("batch_extract", job_id)


def _checkpoint_key(job_id: str) -> str:
    return f"pawgrab:crawl:{job_id}:checkpoint"


async def save_checkpoint(job_id: str, *, visited: set[str], queue: list[tuple[str, int]], pages_scraped: int, cookie_jar: dict[str, str]) -> None:
    redis = await get_redis()
    await redis.set(
        _checkpoint_key(job_id),
        orjson.dumps(
            {
                "visited": list(visited),
                "queue": queue,
                "pages_scraped": pages_scraped,
                "cookie_jar": cookie_jar,
            }
        ).decode(),
        ex=7200,
    )


async def load_checkpoint(job_id: str) -> dict | None:
    redis = await get_redis()
    raw = await redis.get(_checkpoint_key(job_id))
    if not raw:
        return None
    try:
        data = orjson.loads(raw)
        data["visited"] = set(data["visited"])
        data["queue"] = [tuple(q) for q in data["queue"]]
        return data
    except (orjson.JSONDecodeError, KeyError):
        return None


async def delete_checkpoint(job_id: str) -> None:
    redis = await get_redis()
    await redis.delete(_checkpoint_key(job_id))


def _pubsub_channel(job_id: str) -> str:
    return f"pawgrab:events:{job_id}"


async def publish_event(job_id: str, event_type: str, data: dict) -> None:
    redis = await get_redis()
    await redis.publish(_pubsub_channel(job_id), orjson.dumps({"type": event_type, **data}).decode())


async def subscribe_events(job_id: str):
    """Yields event strings from Redis pub/sub, or None as a heartbeat signal."""
    redis = await get_redis()
    pubsub = redis.pubsub()
    channel = _pubsub_channel(job_id)
    await pubsub.subscribe(channel)
    deadline = time.monotonic() + settings.sse_max_duration
    last_event = time.monotonic()
    try:
        while True:
            if time.monotonic() > deadline:
                logger.info("sse_max_duration_exceeded", job_id=job_id)
                break
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is not None and message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode()
                last_event = time.monotonic()
                yield data
                try:
                    parsed = orjson.loads(data)
                    if parsed.get("type") in ("completed", "failed"):
                        break
                except orjson.JSONDecodeError:
                    pass
            elif (time.monotonic() - last_event) >= _HEARTBEAT_INTERVAL:
                last_event = time.monotonic()
                yield None
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
