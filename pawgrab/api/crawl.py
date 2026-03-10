"""POST /v1/crawl and GET /v1/crawl/{job_id} — async crawl endpoints."""

from __future__ import annotations

import asyncio
import json
import re

import structlog
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from pawgrab.config import settings
from pawgrab.models.crawl import CrawlRequest, CrawlResponse, CrawlStatus
from pawgrab.queue.manager import create_job, get_job, subscribe_events

logger = structlog.get_logger()
router = APIRouter()

# Shared arq pool — created once, reused across requests
_arq_pool = None
_arq_lock = asyncio.Lock()

_JOB_ID_RE = re.compile(r"^[a-f0-9]{12}$")


async def _get_arq_pool():
    global _arq_pool
    if _arq_pool is None:
        async with _arq_lock:
            if _arq_pool is None:
                redis_settings = RedisSettings.from_dsn(settings.redis_url)
                _arq_pool = await create_pool(redis_settings)
    return _arq_pool


@router.post("/crawl", response_model=CrawlResponse, status_code=202)
async def start_crawl(req: CrawlRequest):
    url = str(req.url)
    formats = [f.value for f in req.formats]
    resume = False

    # If resuming a previous crawl, reuse its job_id
    if req.resume_job_id:
        if not _JOB_ID_RE.match(req.resume_job_id):
            raise HTTPException(status_code=400, detail="Invalid resume_job_id format")
        existing = await get_job(req.resume_job_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Resume job not found")
        job_id = req.resume_job_id
        resume = True
    else:
        webhook = str(req.webhook_url) if req.webhook_url else None
        job_id = await create_job(url, req.max_pages, req.max_depth, formats, webhook_url=webhook)

    try:
        pool = await _get_arq_pool()
        await pool.enqueue_job(
            "crawl_job",
            job_id,
            url,
            req.max_pages,
            req.max_depth,
            json.dumps(formats),
            resume,
            req.strategy.value,
            json.dumps(req.allowed_domains) if req.allowed_domains else None,
            json.dumps(req.blocked_domains) if req.blocked_domains else None,
            json.dumps(req.include_path_patterns) if req.include_path_patterns else None,
            json.dumps(req.exclude_path_patterns) if req.exclude_path_patterns else None,
            json.dumps(req.keywords) if req.keywords else None,
        )
    except Exception as exc:
        logger.error("crawl_enqueue_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="Queue service unavailable")

    return CrawlResponse(job_id=job_id, status=CrawlStatus.QUEUED, url=url)


@router.get("/crawl/{job_id}")
async def get_crawl_status(
    job_id: str,
    page: int = Query(default=1, ge=1, description="Results page number"),
    limit: int = Query(default=50, ge=1, le=200, description="Results per page"),
):
    if not _JOB_ID_RE.match(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    job = await get_job(job_id, page=page, limit=limit)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/crawl/{job_id}/stream")
async def stream_crawl_events(job_id: str):
    """SSE endpoint for real-time crawl progress."""
    if not _JOB_ID_RE.match(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    job = await get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    # If job already completed/failed, send final event immediately
    if job.status in (CrawlStatus.COMPLETED, CrawlStatus.FAILED):
        event_type = job.status.value
        data = json.dumps({
            "type": event_type,
            "pages_scraped": job.pages_scraped,
            **({"error": job.error} if job.error else {}),
        })

        async def _final():
            yield f"event: {event_type}\ndata: {data}\n\n"

        return StreamingResponse(
            _final(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def _stream():
        async for event_data in subscribe_events(job_id):
            try:
                parsed = json.loads(event_data)
                event_type = parsed.pop("type", "message")
                yield f"event: {event_type}\ndata: {json.dumps(parsed)}\n\n"
            except json.JSONDecodeError:
                yield f"data: {event_data}\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
