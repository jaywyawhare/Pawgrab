"""POST /v1/crawl and GET /v1/crawl/{job_id}."""

from __future__ import annotations

import orjson
import structlog
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from pawgrab.exceptions import PawgrabError
from pawgrab.models.common import JOB_ID_RESPONSES, QUEUE_RESPONSES
from pawgrab.models.crawl import CrawlRequest, CrawlResponse, CrawlStatus
from pawgrab.queue.manager import (
    cancel_crawl_job,
    create_job,
    get_job,
    list_crawl_jobs,
    subscribe_events,
)
from pawgrab.queue.pool import JOB_ID_RE, get_arq_pool

logger = structlog.get_logger()
router = APIRouter(tags=["Crawl"])

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _require_valid_job_id(job_id: str) -> None:
    if not JOB_ID_RE.match(job_id):
        raise PawgrabError.invalid_job_id()


async def _require_job(job_id: str, **kwargs):
    job = await get_job(job_id, **kwargs)
    if job is None:
        raise PawgrabError.not_found(job_id)
    return job


@router.post(
    "/crawl",
    response_model=CrawlResponse,
    status_code=202,
    responses={**JOB_ID_RESPONSES, **QUEUE_RESPONSES},
)
async def start_crawl(req: CrawlRequest):
    """Start an async crawl job. Returns a job ID immediately."""
    url = str(req.url)
    formats = [f.value for f in req.formats]
    resume = False

    if req.resume_job_id:
        _require_valid_job_id(req.resume_job_id)
        await _require_job(req.resume_job_id)
        job_id = req.resume_job_id
        resume = True
    else:
        webhook = str(req.webhook_url) if req.webhook_url else None
        job_id = await create_job(url, req.max_pages, req.max_depth, formats, webhook_url=webhook)

    try:
        pool = await get_arq_pool()
        await pool.enqueue_job(
            "crawl_job",
            job_id,
            url,
            req.max_pages,
            req.max_depth,
            orjson.dumps(formats).decode(),
            resume,
            req.strategy.value,
            orjson.dumps(req.allowed_domains).decode() if req.allowed_domains else None,
            orjson.dumps(req.blocked_domains).decode() if req.blocked_domains else None,
            orjson.dumps(req.include_path_patterns).decode() if req.include_path_patterns else None,
            orjson.dumps(req.exclude_path_patterns).decode() if req.exclude_path_patterns else None,
            orjson.dumps(req.keywords).decode() if req.keywords else None,
        )
    except Exception as exc:
        logger.error("crawl_enqueue_failed", error=str(exc))
        raise PawgrabError.queue_unavailable() from exc

    return CrawlResponse(job_id=job_id, status=CrawlStatus.QUEUED, url=url)


@router.get("/crawl")
async def list_crawls(
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=50, ge=1, le=200, description="Jobs per page"),
):
    """List crawl jobs (newest first) with their status."""
    jobs, total = await list_crawl_jobs(page=page, limit=limit)
    return {"jobs": jobs, "total": total, "page": page, "limit": limit, "has_next": page * limit < total}


@router.delete(
    "/crawl/{job_id}",
    responses=JOB_ID_RESPONSES,
)
async def cancel_crawl(job_id: str):
    """Request cancellation of a running crawl job (graceful stop between pages)."""
    _require_valid_job_id(job_id)
    ok = await cancel_crawl_job(job_id)
    if not ok:
        raise PawgrabError.not_found(job_id)
    return {"job_id": job_id, "status": "cancelling"}


@router.get(
    "/crawl/{job_id}",
    responses=JOB_ID_RESPONSES,
)
async def get_crawl_status(
    job_id: str,
    page: int = Query(default=1, ge=1, description="Results page number"),
    limit: int = Query(default=50, ge=1, le=200, description="Results per page"),
):
    """Get the current status and results of a crawl job."""
    _require_valid_job_id(job_id)
    return await _require_job(job_id, page=page, limit=limit)


@router.get(
    "/crawl/{job_id}/stream",
    responses=JOB_ID_RESPONSES,
)
async def stream_crawl_events(job_id: str):
    """Stream real-time crawl progress via Server-Sent Events."""
    _require_valid_job_id(job_id)
    job = await _require_job(job_id)

    if job.status in (CrawlStatus.COMPLETED, CrawlStatus.FAILED):
        event_type = job.status.value
        data = orjson.dumps(
            {
                "type": event_type,
                "pages_scraped": job.pages_scraped,
                **({"error": job.error} if job.error else {}),
            }
        ).decode()

        async def _final():
            yield f"event: {event_type}\ndata: {data}\n\n"

        return StreamingResponse(
            _final(),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    async def _stream():
        async for event_data in subscribe_events(job_id):
            if event_data is None:
                yield ": heartbeat\n\n"
                continue
            try:
                parsed = orjson.loads(event_data)
                event_type = parsed.pop("type", "message")
                yield f"event: {event_type}\ndata: {orjson.dumps(parsed).decode()}\n\n"
            except orjson.JSONDecodeError:
                yield f"data: {event_data}\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
