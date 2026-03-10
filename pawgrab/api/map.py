"""POST /v1/map — sitemap discovery endpoint."""

import structlog
from fastapi import APIRouter, HTTPException

from pawgrab.engine.sitemap import discover_urls
from pawgrab.models.map import MapRequest, MapResponse

logger = structlog.get_logger()
router = APIRouter()


@router.post("/map", response_model=MapResponse)
async def map_site(req: MapRequest):
    url = str(req.url)

    try:
        urls, source = await discover_urls(
            url,
            include_subdomains=req.include_subdomains,
            limit=req.limit,
        )
        return MapResponse(
            success=True,
            url=url,
            urls=urls,
            total=len(urls),
            source=source,
        )
    except Exception as exc:
        logger.error("map_failed", url=url, error=str(exc))
        raise HTTPException(status_code=502, detail="Failed to discover URLs")
