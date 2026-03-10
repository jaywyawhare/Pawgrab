"""POST /v1/batch/scrape and GET /v1/batch/{job_id} — batch scraping endpoints."""

from __future__ import annotations

import asyncio
import json
import re

import structlog
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, HTTPException, Query

from pawgrab.config import settings
from pawgrab.models.batch import BatchJobStatus, BatchScrapeRequest, BatchScrapeResponse
from pawgrab.queue.manager import create_batch_job, get_batch_job

logger = structlog.get_logger()
router = APIRouter()

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


@router.post("/batch/scrape", response_model=BatchScrapeResponse, status_code=202)
async def start_batch_scrape(req: BatchScrapeRequest):
    urls = [str(u) for u in req.urls]
    formats = [f.value for f in req.formats]
    webhook = str(req.webhook_url) if req.webhook_url else None

    job_id = await create_batch_job(urls, formats, webhook_url=webhook)

    try:
        pool = await _get_arq_pool()
        await pool.enqueue_job(
            "batch_scrape_job",
            job_id,
            json.dumps(urls),
            json.dumps(formats),
        )
    except Exception as exc:
        logger.error("batch_enqueue_failed", error=str(exc))
        raise HTTPException(status_code=503, detail="Queue service unavailable")

    return BatchScrapeResponse(job_id=job_id, status="queued", total_urls=len(urls))


@router.get("/batch/{job_id}", response_model=BatchJobStatus)
async def get_batch_status(
    job_id: str,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
):
    if not _JOB_ID_RE.match(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    job = await get_batch_job(job_id, page=page, limit=limit)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
