"""POST /v1/batch/scrape and GET /v1/batch/{job_id}."""

from __future__ import annotations

import orjson
import structlog
from fastapi import APIRouter, Query

from pawgrab.exceptions import PawgrabError
from pawgrab.models.batch import BatchJobStatus, BatchScrapeRequest, BatchScrapeResponse
from pawgrab.models.batch_extract import BatchExtractJobStatus, BatchExtractRequest, BatchExtractResponse
from pawgrab.models.common import JOB_ID_RESPONSES, JobStatus, QUEUE_RESPONSES
from pawgrab.queue.manager import create_batch_extract_job, create_batch_job, get_batch_extract_job, get_batch_job
from pawgrab.queue.pool import JOB_ID_RE, get_arq_pool


def _require_valid_job_id(job_id: str) -> None:
    if not JOB_ID_RE.match(job_id):
        raise PawgrabError.invalid_job_id()

logger = structlog.get_logger()
router = APIRouter(tags=["Batch"])


@router.post(
    "/batch/scrape",
    response_model=BatchScrapeResponse,
    status_code=202,
    responses=QUEUE_RESPONSES,
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
            "batch_scrape_job", job_id,
            orjson.dumps(urls).decode(), orjson.dumps(formats).decode(),
        )
    except Exception as exc:
        logger.error("batch_enqueue_failed", error=str(exc))
        raise PawgrabError.queue_unavailable()

    return BatchScrapeResponse(job_id=job_id, status=JobStatus.QUEUED, total_urls=len(urls))


@router.get(
    "/batch/{job_id}",
    response_model=BatchJobStatus,
    responses=JOB_ID_RESPONSES,
)
async def get_batch_status(
    job_id: str,
    page: int = Query(default=1, ge=1, description="Results page number"),
    limit: int = Query(default=50, ge=1, le=200, description="Results per page"),
):
    """Get the current status and results of a batch scrape job."""
    _require_valid_job_id(job_id)
    job = await get_batch_job(job_id, page=page, limit=limit)
    if job is None:
        raise PawgrabError.not_found(job_id)
    return job


@router.post(
    "/batch/extract",
    response_model=BatchExtractResponse,
    status_code=202,
    responses=QUEUE_RESPONSES,
)
async def start_batch_extract(req: BatchExtractRequest):
    """Start an async batch extraction job for multiple URLs."""
    urls = [str(u) for u in req.urls]
    webhook = str(req.webhook_url) if req.webhook_url else None

    job_id = await create_batch_extract_job(urls, req.strategy.value, webhook_url=webhook)

    try:
        pool = await get_arq_pool()
        await pool.enqueue_job(
            "batch_extract_job", job_id,
            orjson.dumps(urls).decode(),
            req.strategy.value,
            req.prompt or "",
            orjson.dumps(req.schema_hint).decode() if req.schema_hint else "",
            orjson.dumps(req.json_schema).decode() if req.json_schema else "",
            orjson.dumps(req.selectors).decode() if req.selectors else "",
            orjson.dumps(req.xpath_queries).decode() if req.xpath_queries else "",
            orjson.dumps(req.patterns).decode() if isinstance(req.patterns, dict) else (req.patterns or ""),
        )
    except Exception as exc:
        logger.error("batch_extract_enqueue_failed", error=str(exc))
        raise PawgrabError.queue_unavailable()

    return BatchExtractResponse(job_id=job_id, status=JobStatus.QUEUED, total_urls=len(urls))


@router.get(
    "/batch/extract/{job_id}",
    response_model=BatchExtractJobStatus,
    responses=JOB_ID_RESPONSES,
)
async def get_batch_extract_status(
    job_id: str,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Get batch extraction job status and results."""
    _require_valid_job_id(job_id)
    job = await get_batch_extract_job(job_id, page=page, limit=limit)
    if job is None:
        raise PawgrabError.not_found(job_id)
    return job
