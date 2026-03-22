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
from pawgrab.models.common import OutputFormat
from pawgrab.models.scrape import PageMetadata, ScrapeResponse
from pawgrab.config import settings
from pawgrab.utils.rate_limiter import guard_url

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
    excluded_tags: list[str] | None = None,
    excluded_selector: str | None = None,
    css_selector: str | None = None,
    word_count_threshold: int | None = None,
    content_filter: str | None = None,
    content_filter_query: str | None = None,
    browser_type: str | None = None,
    geolocation: dict[str, float] | None = None,
    text_mode: bool = False,
    scroll_to_bottom: bool = False,
    capture_network: bool = False,
    capture_console: bool = False,
    capture_mhtml: bool = False,
    extract_media: bool = False,
    capture_ssl: bool = False,
    capture_websocket: bool = False,
    llm_ready: bool = False,
    cache_ttl: int | None = None,
    session_id: str | None = None,
    hooks: object | None = None,
) -> ScrapeResponse:
    """Full scrape pipeline: robots → rate-limit → fetch → clean → convert."""
    if formats is None:
        formats = [OutputFormat.MARKDOWN]

    await guard_url(url)

    # Cache lookup
    effective_cache_ttl = cache_ttl if cache_ttl is not None else settings.cache_ttl
    cache_params = {
        "formats": [f.value for f in formats],
        "wait_for_js": wait_for_js,
        "css_selector": css_selector,
        "excluded_tags": excluded_tags,
        "excluded_selector": excluded_selector,
        "content_filter": content_filter,
        "fit_markdown_query": fit_markdown_query,
    }
    if effective_cache_ttl > 0:
        from pawgrab.engine.cache import get_cached
        cached = await get_cached(url, cache_params)
        if cached:
            resp = ScrapeResponse(**cached)
            resp.cache_hit = True
            return resp

    # Session: merge persisted cookies
    if session_id:
        from pawgrab.engine.sessions import get_session, merge_cookies_for_session
        session_data = await get_session(session_id)
        if session_data:
            session_cookies = session_data.get("cookies", {})
            if session_cookies:
                cookies = {**session_cookies, **(cookies or {})}
            session_headers = session_data.get("headers", {})
            if session_headers:
                headers = {**session_headers, **(headers or {})}

    if hooks:
        await hooks.fire("before_fetch", url=url)

    effective_wait = wait_for_js
    needs_browser_features = (
        screenshot or pdf or actions or scroll_to_bottom
        or capture_network or capture_console or capture_mhtml
        or text_mode or geolocation or capture_websocket
    )
    if needs_browser_features and effective_wait is None:
        effective_wait = True

    fetch_kwargs = {
        "wait_for_js": effective_wait, "timeout": timeout,
        "browser_pool": browser_pool, "proxy_pool": proxy_pool,
        "headers": headers, "cookies": cookies,
        "capture_screenshot": screenshot, "screenshot_fullpage": screenshot_fullpage,
        "capture_pdf": pdf, "actions": actions,
        "browser_type": browser_type, "geolocation": geolocation,
        "text_mode": text_mode, "scroll_to_bottom": scroll_to_bottom,
        "capture_network": capture_network, "capture_console": capture_console,
        "capture_mhtml": capture_mhtml, "capture_ssl": capture_ssl,
        "capture_websocket": capture_websocket,
        "session_id": session_id,
    }
    result = await fetch_page(url, **fetch_kwargs)

    if hooks:
        await hooks.fire("after_fetch", url=url, result=result)

    pdf_warning: str | None = None
    if result.content_bytes is not None:
        text, pdf_warning = extract_pdf_text(result.content_bytes)
        if text:
            result.html = pdf_text_to_html(text)
        elif pdf_warning:
            logger.warning("pdf_extraction_warning", url=url, warning=pdf_warning)

    if hooks:
        await hooks.fire("before_extract", url=url, html=result.html)

    content_kwargs = {
        "excluded_tags": excluded_tags, "excluded_selector": excluded_selector,
        "css_selector": css_selector, "word_count_threshold": word_count_threshold,
        "content_filter": content_filter, "content_filter_query": content_filter_query,
    }
    response = build_response(
        result, formats=formats, include_metadata=include_metadata,
        citations=citations, fit_markdown_query=fit_markdown_query,
        fit_markdown_top_k=fit_markdown_top_k, **content_kwargs,
    )

    if llm_ready and response.markdown:
        response.markdown = _clean_for_llm(response.markdown)

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
    if result.websocket_messages:
        response.websocket_messages = result.websocket_messages

    if include_metadata and response.metadata:
        response.metadata.retry_count = result.retry_count

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
        await load_content(url)  # populates in-memory cache used by compare_content
        response.diff = compare_content(url, text_content)
        await store_content(url, text_content, ttl=monitor_ttl)

    if monitor and result.screenshot_bytes:
        from pawgrab.engine.diff import compare_screenshots
        response.screenshot_diff = await compare_screenshots(url, result.screenshot_bytes, ttl=monitor_ttl)

    # Session: persist cookies from response
    if session_id and result.cookies:
        try:
            from pawgrab.engine.sessions import merge_cookies_for_session
            await merge_cookies_for_session(session_id, result.cookies)
        except Exception:
            pass

    # Cache store — only cache successful, non-error responses
    status = response.metadata.status_code if response.metadata else 200
    if effective_cache_ttl > 0 and response.success and status < 400:
        from pawgrab.engine.cache import set_cached
        await set_cached(url, cache_params, response.model_dump(), ttl=effective_cache_ttl)

    return response


def build_response(
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
    cleaned = extract_content(
        result.html, url=result.url,
        excluded_tags=excluded_tags, excluded_selector=excluded_selector,
        css_selector=css_selector, word_count_threshold=word_count_threshold,
        content_filter=content_filter, content_filter_query=content_filter_query,
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
                if fit_markdown_query:
                    md = fit_markdown(md, fit_markdown_query, top_k=fit_markdown_top_k)
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
            title=cleaned.title, description=cleaned.description,
            language=cleaned.language, url=result.url,
            status_code=result.status_code, word_count=word_count(text_content),
        )

    if include_metadata and response.metadata:
        from pawgrab.utils.tokens import estimate_tokens
        response.metadata.token_count_estimate = estimate_tokens(text_content)

    return response


def _clean_for_llm(markdown: str) -> str:
    """Strip navigation links, image refs, HTML comments, and excess whitespace."""
    import re
    markdown = re.sub(r'^\s*\[.*?\]\(#.*?\)\s*$', '', markdown, flags=re.MULTILINE)
    markdown = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', r'\1', markdown)
    markdown = re.sub(r'\n{3,}', '\n\n', markdown)
    markdown = re.sub(r'<!--.*?-->', '', markdown, flags=re.DOTALL)
    markdown = re.sub(r'\[([^\]]*)\]\(\s*\)', r'\1', markdown)
    return markdown.strip()
