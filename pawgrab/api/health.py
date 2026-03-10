"""Health check endpoints."""

import structlog
from fastapi import APIRouter
from starlette.responses import JSONResponse

logger = structlog.get_logger()
router = APIRouter()


@router.get("/health")
async def health():
    """Health check — verifies Redis connectivity when available."""
    checks = {"api": "ok"}

    try:
        from pawgrab.queue.manager import get_redis
        redis = await get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"

    status = "ok" if checks.get("redis") == "ok" else "degraded"
    return {"status": status, "checks": checks}


@router.get("/status")
async def status():
    return {
        "status": "ok",
        "version": "0.0.1",
        "service": "pawgrab",
    }
