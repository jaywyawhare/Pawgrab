"""Metrics and observability endpoints."""

import hashlib

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from pawgrab.engine.analytics import usage_tracker
from pawgrab.engine.metrics import metrics
from pawgrab.exceptions import ErrorCode, PawgrabError

router = APIRouter(tags=["Metrics"])


def _caller_key(request: Request) -> str:
    raw = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    return hashlib.sha256(raw.encode()).hexdigest()[:16] if raw else "anonymous"


@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics():
    """Prometheus-compatible metrics endpoint."""
    return metrics.to_prometheus()


@router.get("/v1/metrics")
async def json_metrics():
    """JSON metrics for dashboards and monitoring."""
    return metrics.to_dict()


@router.get("/v1/metrics/browser-pool")
async def browser_pool_metrics():
    from pawgrab.dependencies import try_browser_pool

    pool = await try_browser_pool()
    if pool is None:
        return {"status": "unavailable", "message": "Browser pool not initialized"}
    return pool.stats()


@router.get("/v1/dead-letters")
async def dead_letters(limit: int = 100):
    """List terminally-failed jobs captured in the dead-letter queue."""
    from pawgrab.queue.manager import get_dead_letters

    limit = max(1, min(limit, 1000))
    entries = await get_dead_letters(limit=limit)
    return {"dead_letters": entries, "count": len(entries)}


@router.get("/v1/usage")
async def usage_summary():
    """Get aggregate usage analytics."""
    return usage_tracker.get_summary()


@router.get("/v1/usage/{client_key}")
async def client_usage(client_key: str, request: Request):
    """Get usage analytics for the calling client.

    A caller may only read their own usage — the path key must match the key
    derived from their credentials (prevents reading another tenant's analytics).
    """
    if client_key != _caller_key(request):
        raise PawgrabError(
            status_code=403,
            code=ErrorCode.INVALID_API_KEY,
            message="You may only read your own usage analytics",
        )
    return usage_tracker.get_usage(client_key)
