"""POST /v1/map — sitemap discovery endpoint."""

import structlog
from fastapi import APIRouter

from pawgrab.engine.sitemap import discover_urls
from pawgrab.exceptions import ErrorCode, PawgrabError
from pawgrab.models.common import ErrorResponse
from pawgrab.models.map import MapRequest, MapResponse

logger = structlog.get_logger()
router = APIRouter(tags=["Map"])


@router.post(
    "/map",
    response_model=MapResponse,
    responses={
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        502: {"model": ErrorResponse, "description": "Failed to discover URLs"},
    },
)
async def map_site(req: MapRequest):
    """Discover all URLs on a website via sitemap.xml, robots.txt, and HTML link crawling.

    Returns a list of discovered URLs and the discovery method used.
    """
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
        raise PawgrabError(
            status_code=502,
            code=ErrorCode.FETCH_FAILED,
            message=f"Failed to discover URLs: {type(exc).__name__}",
        )
