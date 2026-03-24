"""Metrics and observability endpoints."""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from pawgrab.engine.analytics import usage_tracker
from pawgrab.engine.metrics import metrics

router = APIRouter(tags=["Metrics"])


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
    return {
        "status": "active",
        "pool_size": pool._pool_size,
        "pages_available": pool._pages.qsize(),
        "degraded": pool._degraded,
        "active_sessions": len(pool._session_contexts),
        **pool.metrics.snapshot(),
    }


@router.get("/v1/usage")
async def usage_summary():
    """Get aggregate usage analytics."""
    return usage_tracker.get_summary()


@router.get("/v1/usage/{client_key}")
async def client_usage(client_key: str):
    """Get usage analytics for a specific client."""
    return usage_tracker.get_usage(client_key)
