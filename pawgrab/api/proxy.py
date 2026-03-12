"""Proxy pool management endpoints."""

from fastapi import APIRouter

from pawgrab.dependencies import get_proxy_pool
from pawgrab.exceptions import ErrorCode, PawgrabError
from pawgrab.models.common import ErrorResponse
from pawgrab.models.proxy import (
    AddProxyRequest,
    AddProxyResponse,
    ProxyListResponse,
    ProxyStatsResponse,
    RemoveProxyResponse,
)

router = APIRouter(tags=["Proxy"])


@router.post("/proxy/pool", response_model=AddProxyResponse)
async def add_proxy(req: AddProxyRequest):
    """Add a proxy to the rotation pool."""
    pool = await get_proxy_pool()
    added = pool.add_proxy(req.url)
    return AddProxyResponse(
        success=added,
        url=req.url,
        message="Proxy added" if added else "Proxy already exists",
    )


@router.delete(
    "/proxy/pool/{proxy_url:path}",
    response_model=RemoveProxyResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Proxy not found in pool"},
    },
)
async def remove_proxy(proxy_url: str):
    """Remove a proxy from the rotation pool."""
    pool = await get_proxy_pool()
    removed = pool.remove_proxy(proxy_url)
    if not removed:
        raise PawgrabError(
            status_code=404,
            code=ErrorCode.RESOURCE_NOT_FOUND,
            message=f"Proxy not found in pool: {proxy_url}",
        )
    return RemoveProxyResponse(success=True, url=proxy_url, message="Proxy removed")


@router.get("/proxy/pool", response_model=ProxyListResponse)
async def list_proxies():
    """List all proxies in the pool with their health status."""
    pool = await get_proxy_pool()
    return ProxyListResponse(proxies=pool.snapshot())


@router.get("/proxy/pool/stats", response_model=ProxyStatsResponse)
async def pool_stats():
    """Get aggregate statistics for the proxy pool."""
    pool = await get_proxy_pool()
    return pool.pool_stats()
