"""POST /v1/scrape endpoint."""

import structlog
from fastapi import APIRouter

from pawgrab.dependencies import try_browser_pool, try_proxy_pool
from pawgrab.engine.scrape_service import scrape_url
from pawgrab.exceptions import ErrorCode, PawgrabError
from pawgrab.models.common import ErrorResponse
from pawgrab.models.scrape import ScrapeRequest, ScrapeResponse

logger = structlog.get_logger()
router = APIRouter(tags=["Scrape"])


@router.post(
    "/scrape",
    response_model=ScrapeResponse,
    responses={
        403: {"model": ErrorResponse, "description": "Blocked by robots.txt"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        502: {"model": ErrorResponse, "description": "Failed to fetch URL"},
        503: {"model": ErrorResponse, "description": "Browser pool unavailable"},
        504: {"model": ErrorResponse, "description": "Request timed out"},
    },
)
async def scrape(req: ScrapeRequest):
    """Scrape a single URL and return content in the requested formats."""
    url = str(req.url)
    warnings: list[str] = []
    pool = await try_browser_pool()
    proxy_pool = await try_proxy_pool()

    if (req.screenshot or req.pdf or req.actions) and pool is None:
        raise PawgrabError(
            status_code=503,
            code=ErrorCode.BROWSER_UNAVAILABLE,
            message="Browser pool unavailable — screenshot, PDF, and actions require a running browser",
        )

    if pool is None and req.wait_for_js is not False:
        warnings.append("Browser pool unavailable — running without JS rendering")

    try:
        response = await scrape_url(
            url,
            **req.model_dump(exclude={"url", "formats", "actions"}),
            formats=req.formats, actions=req.actions,
            browser_pool=pool, proxy_pool=proxy_pool,
        )
        if warnings:
            response.warnings = warnings + response.warnings
        return response
    except PermissionError:
        raise PawgrabError(
            status_code=403, code=ErrorCode.ROBOTS_BLOCKED,
            message="Blocked by robots.txt",
        ) from None
    except TimeoutError:
        raise PawgrabError.timeout(req.timeout) from None
    except Exception as exc:
        logger.error("scrape_failed", url=url, error=str(exc))
        raise PawgrabError.fetch_failed(exc) from exc
