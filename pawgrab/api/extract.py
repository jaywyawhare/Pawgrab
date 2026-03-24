"""POST /v1/extract endpoint."""

import structlog
from fastapi import APIRouter

from pawgrab.ai.extractor import extract_from_url
from pawgrab.config import settings
from pawgrab.dependencies import try_browser_pool
from pawgrab.engine.extractors import auto_generate_schema, get_extractor
from pawgrab.engine.fetcher import fetch_page
from pawgrab.engine.table_extractor import extract_tables
from pawgrab.exceptions import ErrorCode, PawgrabError
from pawgrab.models.common import ErrorResponse
from pawgrab.models.extract import ExtractionStrategy, ExtractRequest, ExtractResponse
from pawgrab.utils.rate_limiter import guard_url

logger = structlog.get_logger()
router = APIRouter(tags=["Extract"])

_PROVIDER_KEY_MAP = {
    "openai": lambda: settings.openai_api_key,
    "anthropic": lambda: settings.anthropic_api_key,
    "gemini": lambda: settings.gemini_api_key,
    "ollama": lambda: "local",
}


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
    pool = await try_browser_pool()

    if req.strategy == ExtractionStrategy.TABLE:
        return await _extract_table(req, url, pool)
    if req.strategy == ExtractionStrategy.LLM:
        return await _extract_llm(req, url, pool)
    return await _extract_non_llm(req, url, pool)


async def _fetch_for_extraction(url: str, req: ExtractRequest, pool) -> object:
    """Shared fetch + robots guard for non-LLM extraction paths."""
    try:
        await guard_url(url)
    except PermissionError as exc:
        raise PawgrabError(status_code=403, code=ErrorCode.ROBOTS_BLOCKED, message=str(exc)) from exc
    try:
        return await fetch_page(url, timeout=req.timeout, browser_pool=pool)
    except TimeoutError:
        raise PawgrabError.timeout(req.timeout) from None
    except Exception as exc:
        raise PawgrabError.fetch_failed(exc) from exc


async def _extract_table(req: ExtractRequest, url: str, pool) -> ExtractResponse:
    result = await _fetch_for_extraction(url, req, pool)
    tables = extract_tables(result.html, table_index=req.table_index)
    return ExtractResponse(success=True, url=url, data=tables)


async def _extract_llm(req: ExtractRequest, url: str, pool) -> ExtractResponse:
    if not req.prompt:
        raise PawgrabError(
            status_code=400, code=ErrorCode.VALIDATION_ERROR,
            message="LLM strategy requires the 'prompt' field — describe what data to extract",
        )
    key_getter = _PROVIDER_KEY_MAP.get(settings.llm_provider)
    if not key_getter or not key_getter():
        raise PawgrabError(
            status_code=503, code=ErrorCode.LLM_UNAVAILABLE,
            message=f"LLM provider '{settings.llm_provider}' not configured. Set the corresponding API key.",
        )

    try:
        data = await extract_from_url(
            url, prompt=req.prompt, schema_hint=req.schema_hint,
            json_schema=req.json_schema, timeout=req.timeout, browser_pool=pool,
            chunk_strategy=req.chunk_strategy, chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap,
        )
    except PermissionError as exc:
        raise PawgrabError(status_code=403, code=ErrorCode.ROBOTS_BLOCKED, message=str(exc)) from exc
    except Exception as exc:
        logger.error("extract_failed", url=url, error=str(exc))
        raise PawgrabError(
            status_code=502, code=ErrorCode.EXTRACTION_FAILED,
            message=f"Extraction failed: {type(exc).__name__}",
        ) from exc

    resp = ExtractResponse(success=True, url=url, data=data)
    if req.auto_schema:
        resp.auto_schema = auto_generate_schema(data)
    return resp


async def _extract_non_llm(req: ExtractRequest, url: str, pool) -> ExtractResponse:
    result = await _fetch_for_extraction(url, req, pool)

    try:
        extractor = get_extractor(
            req.strategy.value, selectors=req.selectors,
            xpath_queries=req.xpath_queries, patterns=req.patterns,
        )
        data = extractor.extract(result.html)
    except ValueError as exc:
        raise PawgrabError(status_code=400, code=ErrorCode.VALIDATION_ERROR, message=str(exc)) from exc
    except Exception as exc:
        logger.error("extraction_failed", url=url, error=str(exc))
        raise PawgrabError(
            status_code=502, code=ErrorCode.EXTRACTION_FAILED,
            message=f"Extraction failed: {type(exc).__name__}",
        ) from exc

    resp = ExtractResponse(success=True, url=url, data=data)
    if req.auto_schema:
        resp.auto_schema = auto_generate_schema(data)
    return resp
