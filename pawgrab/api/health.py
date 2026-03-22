"""Health check endpoints."""

import asyncio

from fastapi import APIRouter

from pawgrab._version import __version__

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health():
    """Returns status (ok/degraded/unhealthy) with per-component checks."""
    checks: dict[str, str] = {"api": "ok"}

    try:
        from pawgrab.queue.manager import get_redis
        redis = await get_redis()
        await asyncio.wait_for(redis.ping(), timeout=3.0)
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"

    try:
        from pawgrab.dependencies import get_browser_pool
        await get_browser_pool()
        checks["browser_pool"] = "ok"
    except Exception:
        checks["browser_pool"] = "unavailable"

    try:
        from pawgrab.engine.dispatcher import _get_memory_percent
        checks["memory"] = f"{round(_get_memory_percent(), 1)}%"
    except Exception:
        checks["memory"] = "unknown"

    if checks["redis"] != "ok":
        status = "unhealthy"
    elif checks["browser_pool"] != "ok":
        status = "degraded"
    else:
        status = "ok"

    return {"status": status, "version": __version__, "checks": checks}


@router.get("/status")
async def status():
    return {"status": "ok", "version": __version__, "service": "pawgrab"}
