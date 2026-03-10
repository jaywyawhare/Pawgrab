"""Proxy pool management endpoints."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from pawgrab.dependencies import get_proxy_pool

router = APIRouter()


class AddProxyRequest(BaseModel):
    url: str


class AddProxyResponse(BaseModel):
    success: bool
    url: str
    message: str


@router.post("/proxy/pool", response_model=AddProxyResponse)
async def add_proxy(req: AddProxyRequest):
    pool = await get_proxy_pool()
    added = pool.add_proxy(req.url)
    return AddProxyResponse(
        success=added,
        url=req.url,
        message="Proxy added" if added else "Proxy already exists",
    )


@router.delete("/proxy/pool/{proxy_url:path}")
async def remove_proxy(proxy_url: str):
    pool = await get_proxy_pool()
    removed = pool.remove_proxy(proxy_url)
    if not removed:
        raise HTTPException(status_code=404, detail="Proxy not found in pool")
    return {"success": True, "url": proxy_url, "message": "Proxy removed"}


@router.get("/proxy/pool")
async def list_proxies():
    pool = await get_proxy_pool()
    return {"proxies": pool.snapshot()}


@router.get("/proxy/pool/stats")
async def pool_stats():
    pool = await get_proxy_pool()
    return pool.pool_stats()
