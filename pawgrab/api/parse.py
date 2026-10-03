"""POST /v1/parse — run raw HTML through the extraction pipeline without fetching."""

import orjson
import structlog
from fastapi import APIRouter

from pawgrab.engine.cleaner import extract_content
from pawgrab.engine.converter import convert
from pawgrab.models.common import ErrorResponse, OutputFormat
from pawgrab.models.parse import ParseRequest, ParseResponse

logger = structlog.get_logger()
router = APIRouter(tags=["Parse"])


@router.post(
    "/parse",
    response_model=ParseResponse,
    responses={422: {"model": ErrorResponse, "description": "Validation error"}},
)
async def parse(req: ParseRequest):
    """Convert raw HTML to clean output formats using the same extraction
    pipeline as /v1/scrape — content cleaning, selector scoping, conversion."""
    try:
        cleaned = extract_content(
            req.html,
            url=req.url or "",
            excluded_tags=req.excluded_tags,
            excluded_selector=req.excluded_selector,
            css_selector=req.css_selector,
            word_count_threshold=req.word_count_threshold,
            content_filter=req.content_filter,
            content_filter_query=req.content_filter_query,
        )

        response = ParseResponse(success=True, title=cleaned.title)
        for fmt in req.formats:
            converted = convert(cleaned.content_html, fmt)
            match fmt:
                case OutputFormat.MARKDOWN:
                    response.markdown = converted
                case OutputFormat.HTML:
                    response.html = converted
                case OutputFormat.TEXT:
                    response.text = converted
                case OutputFormat.JSON:
                    response.json_data = orjson.loads(converted)
                case OutputFormat.CSV:
                    response.csv_data = converted
                case OutputFormat.XML:
                    response.xml_data = converted
        return response
    except Exception as exc:
        logger.warning("parse_failed", error=str(exc))
        return ParseResponse(success=False, error=f"Failed to parse HTML: {type(exc).__name__}")
