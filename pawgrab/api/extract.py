"""POST /v1/extract endpoint."""

import structlog
from fastapi import APIRouter

from pawgrab.ai.extractor import extract_from_url
from pawgrab.config import settings
from pawgrab.dependencies import get_browser_pool
from pawgrab.exceptions import ErrorCode, PawgrabError
from pawgrab.models.common import ErrorResponse
from pawgrab.models.extract import ExtractRequest, ExtractResponse, ExtractionStrategy

logger = structlog.get_logger()
router = APIRouter(tags=["Extract"])


@router.post(
    "/extract",
    response_model=ExtractResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid extraction request"},
        403: {"model": ErrorResponse, "description": "Blocked by robots.txt"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        502: {"model": ErrorResponse, "description": "Failed to fetch URL"},
        503: {"model": ErrorResponse, "description": "LLM provider not configured"},
        504: {"model": ErrorResponse, "description": "Request timed out"},
    },
)
async def extract(req: ExtractRequest):
    """Extract structured data from a URL using LLM, CSS, XPath, or regex."""
    url = str(req.url)

    try:
        pool = await get_browser_pool()
    except Exception:
        pool = None

    if req.strategy == ExtractionStrategy.LLM:
        return await _extract_llm(req, url, pool)
    return await _extract_non_llm(req, url, pool)


async def _extract_llm(req: ExtractRequest, url: str, pool):
    if not req.prompt:
        raise PawgrabError(
            status_code=400,
            code=ErrorCode.VALIDATION_ERROR,
            message="LLM strategy requires the 'prompt' field — describe what data to extract",
        )
    if not settings.openai_api_key:
        raise PawgrabError(
            status_code=503,
            code=ErrorCode.LLM_UNAVAILABLE,
            message="LLM provider not configured. Set PAWGRAB_OPENAI_API_KEY environment variable.",
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
        raise PawgrabError(
            status_code=403,
            code=ErrorCode.ROBOTS_BLOCKED,
            message=str(exc),
        )
    except Exception as exc:
        logger.error("extract_failed", url=url, error=str(exc))
        raise PawgrabError(
            status_code=502,
            code=ErrorCode.EXTRACTION_FAILED,
            message=f"Extraction failed: {type(exc).__name__}",
        )


async def _extract_non_llm(req: ExtractRequest, url: str, pool):
    from pawgrab.engine.extractors import auto_generate_schema, get_extractor
    from pawgrab.engine.fetcher import fetch_page
    from pawgrab.engine.robots import is_allowed
    from pawgrab.utils.rate_limiter import wait_for_slot

    if not await is_allowed(url):
        raise PawgrabError(
            status_code=403,
            code=ErrorCode.ROBOTS_BLOCKED,
            message=f"URL blocked by robots.txt: {url}",
        )

    await wait_for_slot(url)

    try:
        result = await fetch_page(url, timeout=req.timeout, browser_pool=pool)
    except TimeoutError:
        raise PawgrabError(
            status_code=504,
            code=ErrorCode.TIMEOUT,
            message=f"Request timed out after {req.timeout}ms",
        )
    except Exception as exc:
        logger.error("fetch_failed", url=url, error=str(exc))
        raise PawgrabError(
            status_code=502,
            code=ErrorCode.FETCH_FAILED,
            message=f"Failed to fetch URL: {type(exc).__name__}",
        )

    try:
        extractor = get_extractor(
            req.strategy.value,
            selectors=req.selectors,
            xpath_queries=req.xpath_queries,
            patterns=req.patterns,
        )
        data = extractor.extract(result.html)
    except ValueError as exc:
        raise PawgrabError(
            status_code=400,
            code=ErrorCode.VALIDATION_ERROR,
            message=str(exc),
        )
    except Exception as exc:
        logger.error("extraction_failed", url=url, error=str(exc))
        raise PawgrabError(
            status_code=502,
            code=ErrorCode.EXTRACTION_FAILED,
            message=f"Extraction failed: {type(exc).__name__}",
        )

    resp = ExtractResponse(success=True, url=url, data=data)
    if req.auto_schema:
        resp.auto_schema = auto_generate_schema(data)
    return resp
