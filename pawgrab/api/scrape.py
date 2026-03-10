"""POST /v1/scrape — single URL scraping endpoint."""

import structlog
from fastapi import APIRouter, HTTPException

from pawgrab.dependencies import get_browser_pool, get_proxy_pool
from pawgrab.engine.scrape_service import scrape_url
from pawgrab.models.scrape import ScrapeRequest, ScrapeResponse

logger = structlog.get_logger()
router = APIRouter()


@router.post("/scrape", response_model=ScrapeResponse)
async def scrape(req: ScrapeRequest):
    url = str(req.url)

    try:
        pool = await get_browser_pool()
    except Exception:
        pool = None

    try:
        proxy_pool = await get_proxy_pool()
    except Exception:
        proxy_pool = None

    # Screenshot/PDF/actions require browser pool
    if (req.screenshot or req.pdf or req.actions) and pool is None:
        raise HTTPException(
            status_code=503,
            detail="Browser pool unavailable — screenshot/PDF/actions require Playwright",
        )

    try:
        return await scrape_url(
            url,
            formats=req.formats,
            wait_for_js=req.wait_for_js,
            timeout=req.timeout,
            include_metadata=req.include_metadata,
            browser_pool=pool,
            proxy_pool=proxy_pool,
            headers=req.headers,
            cookies=req.cookies,
            screenshot=req.screenshot,
            screenshot_fullpage=req.screenshot_fullpage,
            pdf=req.pdf,
            monitor=req.monitor,
            monitor_ttl=req.monitor_ttl,
            citations=req.citations,
            fit_markdown_query=req.fit_markdown_query,
            fit_markdown_top_k=req.fit_markdown_top_k,
            actions=req.actions,
            excluded_tags=req.excluded_tags,
            excluded_selector=req.excluded_selector,
            css_selector=req.css_selector,
            word_count_threshold=req.word_count_threshold,
            content_filter=req.content_filter,
            content_filter_query=req.content_filter_query,
            browser_type=req.browser_type,
            geolocation=req.geolocation,
            text_mode=req.text_mode,
            scroll_to_bottom=req.scroll_to_bottom,
            capture_network=req.capture_network,
            capture_console=req.capture_console,
            capture_mhtml=req.capture_mhtml,
            extract_media=req.extract_media,
            capture_ssl=req.capture_ssl,
        )
    except PermissionError:
        raise HTTPException(status_code=403, detail="Blocked by robots.txt")
    except Exception as exc:
        logger.error("scrape_failed", url=url, error=str(exc))
        raise HTTPException(status_code=502, detail="Failed to fetch URL")
