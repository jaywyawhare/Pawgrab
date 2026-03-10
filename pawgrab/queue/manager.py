"""Job management via Redis."""

from __future__ import annotations

import asyncio
import uuid

import orjson

import structlog
from redis.asyncio import Redis

from pawgrab.config import settings
from pawgrab.models.crawl import CrawlJobStatus, CrawlStatus
from pawgrab.queue.pool import JOB_ID_RE

logger = structlog.get_logger()

_redis: Redis | None = None
_redis_lock = asyncio.Lock()


async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        async with _redis_lock:
            if _redis is None:
                _redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis():
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def _job_key(job_id: str) -> str:
    return f"pawgrab:crawl:{job_id}"


def _results_key(job_id: str) -> str:
    return f"pawgrab:crawl:{job_id}:results"


async def create_job(
    url: str,
    max_pages: int,
    max_depth: int,
    formats: list[str],
    *,
    webhook_url: str | None = None,
) -> str:
    job_id = uuid.uuid4().hex[:12]
    redis = await get_redis()
    job_data = {
        "job_id": job_id,
        "status": CrawlStatus.QUEUED.value,
        "url": url,
        "max_pages": max_pages,
        "max_depth": max_depth,
        "formats": orjson.dumps(formats).decode(),
        "pages_scraped": 0,
        "error": "",
        "webhook_url": webhook_url or "",
    }
    await redis.hset(_job_key(job_id), mapping=job_data)
    await redis.expire(_job_key(job_id), 3600)
    return job_id


async def get_webhook_url(job_id: str) -> str | None:
    """Get the webhook URL for a job, if any."""
    redis = await get_redis()
    url = await redis.hget(_job_key(job_id), "webhook_url")
    return url if url else None


async def get_job(
    job_id: str,
    *,
    page: int = 1,
    limit: int = 50,
) -> CrawlJobStatus | None:
    """Get job status with paginated results."""
    if not JOB_ID_RE.match(job_id):
        return None

    redis = await get_redis()
    data = await redis.hgetall(_job_key(job_id))
    if not data:
        return None

    # Paginated results from the Redis list
    start = (page - 1) * limit
    end = start + limit - 1
    raw_results = await redis.lrange(_results_key(job_id), start, end)

    results = []
    for r in raw_results:
        try:
            results.append(orjson.loads(r))
        except orjson.JSONDecodeError:
            logger.warning("corrupt_result_entry", job_id=job_id)

    return CrawlJobStatus(
        job_id=data["job_id"],
        status=CrawlStatus(data["status"]),
        pages_scraped=int(data.get("pages_scraped", 0)),
        results=results,
        error=data.get("error") or None,
    )


async def update_job(
    job_id: str,
    *,
    status: CrawlStatus | None = None,
    pages_scraped: int | None = None,
    error: str | None = None,
):
    """Update job metadata fields (not results)."""
    redis = await get_redis()
    updates: dict = {}
    if status is not None:
        updates["status"] = status.value
    if pages_scraped is not None:
        updates["pages_scraped"] = pages_scraped
    if error is not None:
        updates["error"] = error
    if updates:
        await redis.hset(_job_key(job_id), mapping=updates)


async def append_result(job_id: str, result_dict: dict):
    """Append a single scrape result — O(1) via Redis RPUSH."""
    redis = await get_redis()
    key = _results_key(job_id)
    await redis.rpush(key, orjson.dumps(result_dict).decode())
    await redis.expire(key, 3600)


def _batch_key(job_id: str) -> str:
    return f"pawgrab:batch:{job_id}"


def _batch_results_key(job_id: str) -> str:
    return f"pawgrab:batch:{job_id}:results"


async def create_batch_job(
    urls: list[str],
    formats: list[str],
    *,
    webhook_url: str | None = None,
) -> str:
    job_id = uuid.uuid4().hex[:12]
    redis = await get_redis()
    job_data = {
        "job_id": job_id,
        "status": CrawlStatus.QUEUED.value,
        "urls": orjson.dumps(urls).decode(),
        "total_urls": len(urls),
        "formats": orjson.dumps(formats).decode(),
        "urls_scraped": 0,
        "error": "",
        "webhook_url": webhook_url or "",
    }
    await redis.hset(_batch_key(job_id), mapping=job_data)
    await redis.expire(_batch_key(job_id), 3600)
    return job_id


async def get_batch_job(
    job_id: str,
    *,
    page: int = 1,
    limit: int = 50,
) -> dict | None:
    if not JOB_ID_RE.match(job_id):
        return None

    redis = await get_redis()
    data = await redis.hgetall(_batch_key(job_id))
    if not data:
        return None

    start = (page - 1) * limit
    end = start + limit - 1
    raw_results = await redis.lrange(_batch_results_key(job_id), start, end)

    results = []
    for r in raw_results:
        try:
            results.append(orjson.loads(r))
        except orjson.JSONDecodeError:
            logger.warning("corrupt_batch_result", job_id=job_id)

    return {
        "job_id": data["job_id"],
        "status": data["status"],
        "urls_scraped": int(data.get("urls_scraped", 0)),
        "total_urls": int(data.get("total_urls", 0)),
        "results": results,
        "error": data.get("error") or None,
    }


async def update_batch_job(
    job_id: str,
    *,
    status: CrawlStatus | None = None,
    urls_scraped: int | None = None,
    error: str | None = None,
):
    redis = await get_redis()
    updates: dict = {}
    if status is not None:
        updates["status"] = status.value
    if urls_scraped is not None:
        updates["urls_scraped"] = urls_scraped
    if error is not None:
        updates["error"] = error
    if updates:
        await redis.hset(_batch_key(job_id), mapping=updates)


async def append_batch_result(job_id: str, result_dict: dict):
    redis = await get_redis()
    key = _batch_results_key(job_id)
    await redis.rpush(key, orjson.dumps(result_dict).decode())
    await redis.expire(key, 3600)


async def get_batch_webhook_url(job_id: str) -> str | None:
    redis = await get_redis()
    url = await redis.hget(_batch_key(job_id), "webhook_url")
    return url if url else None


def _checkpoint_key(job_id: str) -> str:
    return f"pawgrab:crawl:{job_id}:checkpoint"


async def save_checkpoint(
    job_id: str,
    *,
    visited: set[str],
    queue: list[tuple[str, int]],
    pages_scraped: int,
    cookie_jar: dict[str, str],
) -> None:
    """Save crawl state to Redis so it can be resumed after a crash."""
    redis = await get_redis()
    data = orjson.dumps({
        "visited": list(visited),
        "queue": queue,
        "pages_scraped": pages_scraped,
        "cookie_jar": cookie_jar,
    }).decode()
    await redis.set(_checkpoint_key(job_id), data, ex=7200)


async def load_checkpoint(job_id: str) -> dict | None:
    """Load a saved crawl checkpoint. Returns None if no checkpoint exists."""
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
    """Remove checkpoint after successful completion."""
    redis = await get_redis()
    await redis.delete(_checkpoint_key(job_id))


def _pubsub_channel(job_id: str) -> str:
    return f"pawgrab:events:{job_id}"


async def publish_event(job_id: str, event_type: str, data: dict) -> None:
    """Publish an SSE event to the Redis channel for a job."""
    redis = await get_redis()
    payload = orjson.dumps({"type": event_type, **data}).decode()
    await redis.publish(_pubsub_channel(job_id), payload)


async def subscribe_events(job_id: str):
    """Async generator that yields SSE events for a job via Redis pub/sub."""
    redis = await get_redis()
    pubsub = redis.pubsub()
    channel = _pubsub_channel(job_id)
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode()
                yield data
                # Stop after terminal events
                try:
                    parsed = orjson.loads(data)
                    if parsed.get("type") in ("completed", "failed"):
                        break
                except orjson.JSONDecodeError:
                    pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
