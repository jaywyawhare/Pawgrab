"""Scrape pipeline: fetch → clean → convert → response."""

from __future__ import annotations

import base64
import orjson
import structlog

from pawgrab.engine.cleaner import extract_content
from pawgrab.engine.converter import (
    convert,
    fit_markdown,
    markdown_with_citations,
)
from pawgrab.utils.text import word_count
from pawgrab.engine.fetcher import FetchResult, fetch_page
from pawgrab.engine.pdf_extractor import extract_pdf_text, pdf_text_to_html
from pawgrab.engine.robots import is_allowed
from pawgrab.models.common import OutputFormat
from pawgrab.models.scrape import PageMetadata, ScrapeResponse
from pawgrab.utils.rate_limiter import wait_for_slot

logger = structlog.get_logger()


async def scrape_url(
    url: str,
    *,
    formats: list[OutputFormat] | None = None,
    wait_for_js: bool | None = None,
    timeout: int = 30_000,
    include_metadata: bool = True,
    browser_pool: object | None = None,
    proxy_pool: object | None = None,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    screenshot: bool = False,
    screenshot_fullpage: bool = True,
    pdf: bool = False,
    monitor: bool = False,
    monitor_ttl: int | None = None,
    citations: bool = False,
    fit_markdown_query: str | None = None,
    fit_markdown_top_k: int = 5,
    actions: list | None = None,
    # Content processing
    excluded_tags: list[str] | None = None,
    excluded_selector: str | None = None,
    css_selector: str | None = None,
    word_count_threshold: int | None = None,
    content_filter: str | None = None,
    content_filter_query: str | None = None,
    # Browser enhancements
    browser_type: str | None = None,
    geolocation: dict[str, float] | None = None,
    text_mode: bool = False,
    scroll_to_bottom: bool = False,
    # Capture options
    capture_network: bool = False,
    capture_console: bool = False,
    capture_mhtml: bool = False,
    extract_media: bool = False,
    capture_ssl: bool = False,
    # Hooks
    hooks: object | None = None,
) -> ScrapeResponse:
    """Full scrape pipeline: robots → rate-limit → fetch → clean → convert."""
    if formats is None:
        formats = [OutputFormat.MARKDOWN]

    if not await is_allowed(url):
        raise PermissionError(f"URL blocked by robots.txt: {url}")

    await wait_for_slot(url)

    if hooks:
        await hooks.fire("before_fetch", url=url)

    effective_wait = wait_for_js
    needs_browser_features = (
        screenshot or pdf or actions or scroll_to_bottom
        or capture_network or capture_console or capture_mhtml
        or text_mode or geolocation
    )
    if needs_browser_features and effective_wait is None:
        effective_wait = True

    result = await fetch_page(
        url,
        wait_for_js=effective_wait,
        timeout=timeout,
        browser_pool=browser_pool,
        proxy_pool=proxy_pool,
        headers=headers,
        cookies=cookies,
        capture_screenshot=screenshot,
        screenshot_fullpage=screenshot_fullpage,
        capture_pdf=pdf,
        actions=actions,
        browser_type=browser_type,
        geolocation=geolocation,
        text_mode=text_mode,
        scroll_to_bottom=scroll_to_bottom,
        capture_network=capture_network,
        capture_console=capture_console,
        capture_mhtml=capture_mhtml,
        capture_ssl=capture_ssl,
    )

    if hooks:
        await hooks.fire("after_fetch", url=url, result=result)

    # PDF content extraction — convert PDF bytes into HTML for the pipeline
    pdf_warning: str | None = None
    if result.content_bytes is not None:
        text, pdf_warning = extract_pdf_text(result.content_bytes)
        if text:
            result.html = pdf_text_to_html(text)
        elif pdf_warning:
            logger.warning("pdf_extraction_warning", url=url, warning=pdf_warning)

    if hooks:
        await hooks.fire("before_extract", url=url, html=result.html)

    response = _build_response(
        result,
        formats=formats,
        include_metadata=include_metadata,
        citations=citations,
        fit_markdown_query=fit_markdown_query,
        fit_markdown_top_k=fit_markdown_top_k,
        excluded_tags=excluded_tags,
        excluded_selector=excluded_selector,
        css_selector=css_selector,
        word_count_threshold=word_count_threshold,
        content_filter=content_filter,
        content_filter_query=content_filter_query,
    )

    if extract_media:
        from pawgrab.engine.media import extract_all_media
        response.media = extract_all_media(result.html, result.url)

    if result.network_requests:
        response.network_requests = result.network_requests
    if result.console_logs:
        response.console_logs = result.console_logs
    if result.mhtml_data:
        response.mhtml_base64 = base64.b64encode(result.mhtml_data).decode()
    if result.ssl_info:
        response.ssl_certificate = result.ssl_info

    if hooks:
        await hooks.fire("after_extract", url=url, response=response)

    if result.action_warnings:
        response.warnings.extend(result.action_warnings)

    if pdf_warning:
        response.warnings.append(pdf_warning)

    if result.screenshot_bytes:
        response.screenshot_base64 = base64.b64encode(result.screenshot_bytes).decode()
    if result.pdf_bytes:
        response.pdf_base64 = base64.b64encode(result.pdf_bytes).decode()

    if monitor:
        from pawgrab.engine.diff import compare_content, load_content, store_content
        text_content = response.markdown or response.text or ""
        await load_content(url)  # populate cache from Redis
        response.diff = compare_content(url, text_content)
        await store_content(url, text_content, ttl=monitor_ttl)

    return response


def _build_response(
    result: FetchResult,
    *,
    formats: list[OutputFormat],
    include_metadata: bool,
    citations: bool = False,
    fit_markdown_query: str | None = None,
    fit_markdown_top_k: int = 5,
    excluded_tags: list[str] | None = None,
    excluded_selector: str | None = None,
    css_selector: str | None = None,
    word_count_threshold: int | None = None,
    content_filter: str | None = None,
    content_filter_query: str | None = None,
) -> ScrapeResponse:
    """Convert a FetchResult into a ScrapeResponse."""
    cleaned = extract_content(
        result.html,
        url=result.url,
        excluded_tags=excluded_tags,
        excluded_selector=excluded_selector,
        css_selector=css_selector,
        word_count_threshold=word_count_threshold,
        content_filter=content_filter,
        content_filter_query=content_filter_query,
    )

    warnings = []
    if result.challenge and result.challenge.detected:
        warnings.append(result.challenge.detail)

    response = ScrapeResponse(success=True, url=result.url, warnings=warnings)

    text_content = ""
    for fmt in formats:
        converted = convert(cleaned.content_html, fmt)
        match fmt:
            case OutputFormat.MARKDOWN:
                md = converted
                # Apply fit_markdown first (filter by relevance)
                if fit_markdown_query:
                    md = fit_markdown(md, fit_markdown_query, top_k=fit_markdown_top_k)
                # Then apply citations
                if citations:
                    md = markdown_with_citations(md)
                response.markdown = md
                text_content = md
            case OutputFormat.HTML:
                response.html = converted
            case OutputFormat.TEXT:
                response.text = converted
                text_content = converted
            case OutputFormat.JSON:
                response.json_data = orjson.loads(converted)
            case OutputFormat.CSV:
                response.csv_data = converted
            case OutputFormat.XML:
                response.xml_data = converted

    if not text_content:
        text_content = convert(cleaned.content_html, OutputFormat.TEXT)

    if include_metadata:
        response.metadata = PageMetadata(
            title=cleaned.title,
            description=cleaned.description,
            language=cleaned.language,
            url=result.url,
            status_code=result.status_code,
            word_count=word_count(text_content),
        )

    return response
