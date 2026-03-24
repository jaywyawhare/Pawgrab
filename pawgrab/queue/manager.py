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
_JOB_TTL = 3600


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


async def _create_job(prefix: str, fields: dict[str, Any], *, webhook_url: str | None = None) -> str:
    job_id = uuid.uuid4().hex[:12]
    redis = await get_redis()
    fields.update({"job_id": job_id, "status": CrawlStatus.QUEUED.value, "error": "", "webhook_url": webhook_url or ""})
    await redis.hset(_key(prefix, job_id), mapping=fields)
    await redis.expire(_key(prefix, job_id), _JOB_TTL)
    return job_id


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
        await redis.hset(_key(prefix, job_id), mapping=updates)


async def _append_result(prefix: str, job_id: str, result_dict: dict) -> None:
    redis = await get_redis()
    key = _results_key(prefix, job_id)
    await redis.rpush(key, orjson.dumps(result_dict).decode())
    await redis.expire(key, _JOB_TTL)


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
