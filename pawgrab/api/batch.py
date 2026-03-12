"""POST /v1/batch/scrape and GET /v1/batch/{job_id}."""

from __future__ import annotations

import orjson
import structlog
from fastapi import APIRouter, Query

from pawgrab.exceptions import ErrorCode, PawgrabError
from pawgrab.models.batch import BatchJobStatus, BatchScrapeRequest, BatchScrapeResponse
from pawgrab.models.common import ErrorResponse, JobStatus
from pawgrab.queue.manager import create_batch_job, get_batch_job
from pawgrab.queue.pool import JOB_ID_RE, get_arq_pool

logger = structlog.get_logger()
router = APIRouter(tags=["Batch"])


@router.post(
    "/batch/scrape",
    response_model=BatchScrapeResponse,
    status_code=202,
    responses={
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        503: {"model": ErrorResponse, "description": "Queue service unavailable"},
    },
)
async def start_batch_scrape(req: BatchScrapeRequest):
    """Start an async batch scrape job for multiple URLs.

    Returns a job ID immediately. Poll GET /v1/batch/{job_id} for results.
    """
    urls = [str(u) for u in req.urls]
    formats = [f.value for f in req.formats]
    webhook = str(req.webhook_url) if req.webhook_url else None

    job_id = await create_batch_job(urls, formats, webhook_url=webhook)

    try:
        pool = await get_arq_pool()
        await pool.enqueue_job(
            "batch_scrape_job",
            job_id,
            orjson.dumps(urls).decode(),
            orjson.dumps(formats).decode(),
        )
    except Exception as exc:
        logger.error("batch_enqueue_failed", error=str(exc))
        raise PawgrabError(
            status_code=503,
            code=ErrorCode.QUEUE_UNAVAILABLE,
            message="Queue service unavailable — is Redis running?",
        )

    return BatchScrapeResponse(job_id=job_id, status=JobStatus.QUEUED, total_urls=len(urls))


@router.get(
    "/batch/{job_id}",
    response_model=BatchJobStatus,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid job ID format"},
        404: {"model": ErrorResponse, "description": "Job not found"},
    },
)
async def get_batch_status(
    job_id: str,
    page: int = Query(default=1, ge=1, description="Results page number"),
    limit: int = Query(default=50, ge=1, le=200, description="Results per page"),
):
    """Get the current status and results of a batch scrape job."""
    if not JOB_ID_RE.match(job_id):
        raise PawgrabError(
            status_code=400,
            code=ErrorCode.VALIDATION_ERROR,
            message="Invalid job ID format — must be a 12-character hex string",
        )

    job = await get_batch_job(job_id, page=page, limit=limit)
    if job is None:
        raise PawgrabError(
            status_code=404,
            code=ErrorCode.RESOURCE_NOT_FOUND,
            message=f"Job not found: {job_id}",
        )
    return job
