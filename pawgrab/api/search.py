"""POST /v1/search — search and scrape endpoint."""

import structlog
from fastapi import APIRouter, HTTPException

from pawgrab.dependencies import get_browser_pool
from pawgrab.engine.scrape_service import scrape_url
from pawgrab.engine.search_provider import search_web
from pawgrab.models.search import SearchRequest, SearchResponse

logger = structlog.get_logger()
router = APIRouter()


@router.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest):
    try:
        urls = await search_web(req.query, num_results=req.num_results)
    except Exception as exc:
        logger.error("search_failed", query=req.query, error=str(exc))
        raise HTTPException(status_code=502, detail="Search provider error")

    if not urls:
        return SearchResponse(success=True, query=req.query, results=[], total=0)

    try:
        pool = await get_browser_pool()
    except Exception:
        pool = None

    results = []
    for url in urls:
        try:
            response = await scrape_url(
                url,
                formats=req.formats,
                include_metadata=req.include_metadata,
                browser_pool=pool,
            )
            results.append(response)
        except Exception as exc:
            logger.warning("search_scrape_failed", url=url, error=str(exc))

    return SearchResponse(
        success=True,
        query=req.query,
        results=results,
        total=len(results),
    )
