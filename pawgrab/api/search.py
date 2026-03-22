"""POST /v1/search — search and scrape endpoint."""

import asyncio

import structlog
from fastapi import APIRouter

from pawgrab.dependencies import try_browser_pool
from pawgrab.engine.scrape_service import scrape_url
from pawgrab.engine.search_provider import search_web
from pawgrab.exceptions import ErrorCode, PawgrabError
from pawgrab.models.common import ErrorResponse
from pawgrab.models.search import SearchRequest, SearchResponse

logger = structlog.get_logger()
router = APIRouter(tags=["Search"])

_SEARCH_CONCURRENCY = 5


@router.post(
    "/search",
    response_model=SearchResponse,
    responses={
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        502: {"model": ErrorResponse, "description": "Search provider error"},
    },
)
async def search(req: SearchRequest):
    """Search the web and scrape each result page.

    Uses the configured search provider (DuckDuckGo, SerpAPI, or Google)
    to find URLs, then scrapes each one in parallel and returns the content.
    """
    try:
        urls = await search_web(req.query, num_results=req.num_results)
    except Exception as exc:
        logger.error("search_failed", query=req.query, error=str(exc))
        raise PawgrabError(
            status_code=502,
            code=ErrorCode.SEARCH_FAILED,
            message=f"Search provider error: {type(exc).__name__}",
        )

    if not urls:
        return SearchResponse(success=True, query=req.query, results=[], total=0)

    pool = await try_browser_pool()

    sem = asyncio.Semaphore(_SEARCH_CONCURRENCY)

    async def _scrape_one(url: str):
        async with sem:
            try:
                response = await scrape_url(
                    url,
                    formats=req.formats,
                    include_metadata=req.include_metadata,
                    browser_pool=pool,
                )
                return url, response, None
            except Exception as exc:
                logger.warning("search_scrape_failed", url=url, error=str(exc))
                return url, None, exc

    outcomes = await asyncio.gather(*[_scrape_one(u) for u in urls])

    results = []
    failed_urls = []
    for url, response, error in outcomes:
        if response is not None:
            results.append(response)
        else:
            failed_urls.append(url)

    return SearchResponse(
        success=len(results) > 0,
        query=req.query,
        results=results,
        total=len(results),
        failed_urls=failed_urls,
    )
