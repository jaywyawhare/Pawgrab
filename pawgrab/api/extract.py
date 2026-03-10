"""POST /v1/extract — structured extraction endpoint."""

import structlog
from fastapi import APIRouter, HTTPException

from pawgrab.ai.extractor import extract_from_url
from pawgrab.config import settings
from pawgrab.dependencies import get_browser_pool
from pawgrab.models.extract import ExtractRequest, ExtractResponse, ExtractionStrategy

logger = structlog.get_logger()
router = APIRouter()


@router.post("/extract", response_model=ExtractResponse)
async def extract(req: ExtractRequest):
    url = str(req.url)

    try:
        pool = await get_browser_pool()
    except Exception:
        pool = None

    # Route to appropriate extractor based on strategy
    if req.strategy == ExtractionStrategy.LLM:
        return await _extract_llm(req, url, pool)
    else:
        return await _extract_non_llm(req, url, pool)


async def _extract_llm(req: ExtractRequest, url: str, pool):
    """LLM-based extraction (original path)."""
    if not req.prompt:
        raise HTTPException(status_code=400, detail="LLM strategy requires 'prompt' field")
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=503,
            detail="OpenAI API key not configured. Set PAWGRAB_OPENAI_API_KEY.",
        )

    try:
        data = await extract_from_url(
            url,
            prompt=req.prompt,
            schema_hint=req.schema_hint,
            json_schema=req.json_schema,
            timeout=req.timeout,
            browser_pool=pool,
            chunk_strategy=req.chunk_strategy,
            chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap,
        )
        resp = ExtractResponse(success=True, url=url, data=data)
        if req.auto_schema:
            from pawgrab.engine.extractors import auto_generate_schema
            resp.auto_schema = auto_generate_schema(data)
        return resp
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        logger.error("extract_failed", url=url, error=str(exc))
        return ExtractResponse(success=False, url=url, error="Extraction failed")


async def _extract_non_llm(req: ExtractRequest, url: str, pool):
    """CSS / XPath / Regex extraction."""
    from pawgrab.engine.extractors import auto_generate_schema, get_extractor
    from pawgrab.engine.fetcher import fetch_page
    from pawgrab.engine.robots import is_allowed
    from pawgrab.utils.rate_limiter import wait_for_slot

    if not await is_allowed(url):
        raise HTTPException(status_code=403, detail=f"URL blocked by robots.txt: {url}")

    await wait_for_slot(url)

    try:
        result = await fetch_page(url, timeout=req.timeout, browser_pool=pool)
    except Exception as exc:
        logger.error("fetch_failed", url=url, error=str(exc))
        return ExtractResponse(success=False, url=url, error="Failed to fetch URL")

    try:
        extractor = get_extractor(
            req.strategy.value,
            selectors=req.selectors,
            xpath_queries=req.xpath_queries,
            patterns=req.patterns,
        )
        data = extractor.extract(result.html)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("extraction_failed", url=url, error=str(exc))
        return ExtractResponse(success=False, url=url, error="Extraction failed")

    resp = ExtractResponse(success=True, url=url, data=data)
    if req.auto_schema:
        resp.auto_schema = auto_generate_schema(data)
    return resp
