"""ARQ worker for async crawl jobs (BFS/DFS/BestFirst with depth/page limits)."""

from __future__ import annotations

import asyncio
import random
from urllib.parse import urlparse

import orjson
import structlog
from bs4 import BeautifulSoup

from pawgrab.config import settings
from pawgrab.engine.crawl_strategy import get_strategy
from pawgrab.engine.fetcher import fetch_page
from pawgrab.engine.scrape_service import scrape_url
from pawgrab.engine.url_filter import (
    ContentTypeFilter,
    DomainFilter,
    DuplicateFilter,
    FilterChain,
    PathFilter,
)
from pawgrab.engine.webhook import send_webhook
from pawgrab.models.common import OutputFormat
from pawgrab.models.crawl import CrawlStatus
from pawgrab.queue.manager import (
    append_batch_result,
    append_result,
    delete_checkpoint,
    get_batch_webhook_url,
    get_webhook_url,
    load_checkpoint,
    publish_event,
    save_checkpoint,
    update_batch_job,
    update_job,
)
from pawgrab.utils.url import is_same_domain, normalize_url, resolve_url

logger = structlog.get_logger()

_MAX_QUEUE_SIZE = 5000


def _is_hidden_link(tag) -> bool:
    """Check if an <a> tag is hidden via inline style or CSS class hints.

    Cloudflare AI Labyrinth and similar traps use hidden links to lure bots
    into infinite crawl loops filled with AI-generated garbage.
    """
    style = (tag.get("style") or "").lower()
    if any(pattern in style for pattern in (
        "display:none", "display: none",
        "visibility:hidden", "visibility: hidden",
        "opacity:0", "opacity: 0",
        "left:-9999", "top:-9999",
        "position:absolute",
    )):
        return True

    parent = tag.parent
    if parent:
        parent_style = (parent.get("style") or "").lower()
        if "display:none" in parent_style or "display: none" in parent_style:
            return True

    if tag.get("aria-hidden") == "true":
        return True

    return False


def _is_noindex_page(html: str) -> bool:
    """Check if a page has a noindex robots meta tag (AI Labyrinth pages often do).

    Parses the actual <meta name="robots"> tag instead of doing a naive string
    search, which false-positives on documentation pages that mention robots.txt.
    """
    try:
        soup = BeautifulSoup(html[:10_000], "html.parser")
        for meta in soup.find_all("meta", attrs={"name": True}):
            if meta.get("name", "").lower() in ("robots", "googlebot"):
                if "noindex" in meta.get("content", "").lower():
                    return True
    except Exception:
        pass
    return False


def _extract_links(
    html: str,
    base_url: str,
    seed_url: str,
    visited: set[str],
    url_filter: FilterChain | None = None,
) -> list[str]:
    """Extract valid same-domain links from HTML."""
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return []

    links = []
    for a_tag in soup.find_all("a", href=True):
        if _is_hidden_link(a_tag):
            continue

        href = resolve_url(base_url, a_tag["href"])
        parsed = urlparse(href)
        if not parsed.scheme or not parsed.netloc:
            continue
        if parsed.scheme not in ("http", "https"):
            continue

        normalized = normalize_url(href)
        if normalized in visited:
            continue

        if not is_same_domain(href, seed_url):
            continue

        if url_filter and not url_filter.accept(href):
            continue

        links.append(href)
    return links


def _build_filter_chain(
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
    include_path_patterns: list[str] | None = None,
    exclude_path_patterns: list[str] | None = None,
) -> FilterChain:
    """Build a composable URL filter chain from crawl request params."""
    chain = FilterChain()

    if allowed_domains or blocked_domains:
        chain.add(DomainFilter(
            allowed_domains=allowed_domains,
            blocked_domains=blocked_domains,
        ))

    if include_path_patterns or exclude_path_patterns:
        chain.add(PathFilter(
            include_patterns=include_path_patterns,
            exclude_patterns=exclude_path_patterns,
        ))

    chain.add(ContentTypeFilter())
    chain.add(DuplicateFilter())

    return chain


async def crawl_job(
    ctx: dict,
    job_id: str,
    url: str,
    max_pages: int,
    max_depth: int,
    formats_json: str,
    resume: bool = False,
    strategy_name: str = "bfs",
    allowed_domains: str | None = None,
    blocked_domains: str | None = None,
    include_path_patterns: str | None = None,
    exclude_path_patterns: str | None = None,
    keywords: str | None = None,
):
    """Crawl using configured strategy (BFS/DFS/BestFirst), respecting depth and page limits.

    Supports crash recovery: state is checkpointed to Redis every 10 pages.
    Pass resume=True to restore from a previous checkpoint.
    """
    formats = [OutputFormat(f) for f in orjson.loads(formats_json)]
    browser_pool = ctx.get("browser_pool")
    proxy_pool = ctx.get("proxy_pool")

    filter_chain = _build_filter_chain(
        allowed_domains=orjson.loads(allowed_domains) if allowed_domains else None,
        blocked_domains=orjson.loads(blocked_domains) if blocked_domains else None,
        include_path_patterns=orjson.loads(include_path_patterns) if include_path_patterns else None,
        exclude_path_patterns=orjson.loads(exclude_path_patterns) if exclude_path_patterns else None,
    )

    kw_list = orjson.loads(keywords) if keywords else None
    strategy = get_strategy(strategy_name, keywords=kw_list)

    await update_job(job_id, status=CrawlStatus.IN_PROGRESS)

    visited: set[str] = set()
    pages_scraped = 0
    cookie_jar: dict[str, str] = {}
    job_error: str | None = None

    if resume:
        checkpoint = await load_checkpoint(job_id)
        if checkpoint:
            visited = checkpoint["visited"]
            for u, d in checkpoint["queue"]:
                strategy.add(u, d)
            pages_scraped = checkpoint["pages_scraped"]
            cookie_jar = checkpoint["cookie_jar"]
            logger.info(
                "crawl_resumed_from_checkpoint",
                job_id=job_id,
                pages_scraped=pages_scraped,
                queue_size=len(strategy),
            )
    else:
        strategy.add(url, 0)

    checkpoint_interval = settings.checkpoint_interval

    try:
        while not strategy.is_empty and pages_scraped < max_pages:
            item = strategy.next()
            if item is None:
                break
            current_url, depth = item
            normalized = normalize_url(current_url)

            if normalized in visited:
                continue
            visited.add(normalized)

            if pages_scraped > 0:
                await asyncio.sleep(random.uniform(0.5, 2.5))

            try:
                raw_result = await fetch_page(
                    current_url,
                    browser_pool=browser_pool,
                    proxy_pool=proxy_pool,
                    cookies=cookie_jar or None,
                )
                cookie_jar.update(raw_result.cookies)
            except Exception as exc:
                logger.warning("crawl_fetch_failed", url=current_url, error=str(exc))
                await publish_event(job_id, "error", {"url": current_url, "error": str(exc)})
                continue

            try:
                from pawgrab.engine.scrape_service import build_response
                response = build_response(raw_result, formats=formats, include_metadata=True)
            except Exception as exc:
                logger.warning("crawl_build_failed", url=current_url, error=str(exc))
                continue

            if not response.success:
                continue

            pages_scraped += 1
            await append_result(job_id, response.model_dump())
            await update_job(job_id, pages_scraped=pages_scraped)
            await publish_event(job_id, "page_scraped", {
                "url": current_url,
                "pages_scraped": pages_scraped,
                "max_pages": max_pages,
            })

            if pages_scraped % checkpoint_interval == 0:
                await save_checkpoint(
                    job_id,
                    visited=visited,
                    queue=strategy.to_list(),
                    pages_scraped=pages_scraped,
                    cookie_jar=cookie_jar,
                )
                logger.debug("crawl_checkpoint_saved", job_id=job_id, pages=pages_scraped)

            if _is_noindex_page(raw_result.html):
                logger.debug("skipping_links_noindex_page", url=current_url)
                continue
            if depth < max_depth and len(strategy) < _MAX_QUEUE_SIZE:
                links = _extract_links(
                    raw_result.html, raw_result.url, url, visited,
                    url_filter=filter_chain,
                )
                for href in links:
                    if len(strategy) >= _MAX_QUEUE_SIZE:
                        break
                    strategy.add(href, depth + 1)

        await update_job(job_id, status=CrawlStatus.COMPLETED)
        await delete_checkpoint(job_id)
        await publish_event(job_id, "completed", {"pages_scraped": pages_scraped})

    except Exception as exc:
        job_error = str(exc)
        logger.error("crawl_job_failed", job_id=job_id, error=job_error)
        await update_job(job_id, status=CrawlStatus.FAILED, error=job_error)
        await publish_event(job_id, "failed", {"error": job_error, "pages_scraped": pages_scraped})
        await save_checkpoint(
            job_id,
            visited=visited,
            queue=strategy.to_list(),
            pages_scraped=pages_scraped,
            cookie_jar=cookie_jar,
        )

    webhook_url = await get_webhook_url(job_id)
    if webhook_url:
        from pawgrab.queue.manager import get_job as _get_job
        job_data = await _get_job(job_id)
        await send_webhook(
            webhook_url,
            job_id=job_id,
            job_type="crawl",
            status=job_data.status.value if job_data else "unknown",
            pages_scraped=pages_scraped,
            error=job_error,
        )


async def batch_scrape_job(ctx: dict, job_id: str, urls_json: str, formats_json: str):
    """Scrape a list of URLs concurrently, storing results as they complete."""
    urls = orjson.loads(urls_json)
    formats = [OutputFormat(f) for f in orjson.loads(formats_json)]
    browser_pool = ctx.get("browser_pool")
    proxy_pool = ctx.get("proxy_pool")

    await update_batch_job(job_id, status=CrawlStatus.IN_PROGRESS)

    urls_scraped = 0
    job_error: str | None = None
    _counter_lock = asyncio.Lock()
    sem = asyncio.Semaphore(settings.worker_max_jobs)

    async def _scrape_one(url: str) -> None:
        nonlocal urls_scraped
        async with sem:
            try:
                response = await scrape_url(
                    url,
                    formats=formats,
                    include_metadata=True,
                    browser_pool=browser_pool,
                    proxy_pool=proxy_pool,
                )
                result = response.model_dump()
            except Exception as exc:
                logger.warning("batch_url_failed", url=url, error=str(exc))
                result = {"success": False, "url": url, "error": str(exc)}

            async with _counter_lock:
                await append_batch_result(job_id, result)
                urls_scraped += 1
                await update_batch_job(job_id, urls_scraped=urls_scraped)

    try:
        await asyncio.gather(*[_scrape_one(url) for url in urls])
        await update_batch_job(job_id, status=CrawlStatus.COMPLETED)

    except Exception as exc:
        job_error = str(exc)
        logger.error("batch_job_failed", job_id=job_id, error=job_error)
        await update_batch_job(job_id, status=CrawlStatus.FAILED, error=job_error)

    webhook_url = await get_batch_webhook_url(job_id)
    if webhook_url:
        await send_webhook(
            webhook_url,
            job_id=job_id,
            job_type="batch",
            status=CrawlStatus.COMPLETED.value if not job_error else CrawlStatus.FAILED.value,
            pages_scraped=urls_scraped,
            total_pages=len(urls),
            error=job_error,
        )


async def batch_extract_job(
    ctx: dict, job_id: str, urls_json: str, strategy: str,
    prompt: str, schema_hint_json: str, json_schema_json: str,
    selectors_json: str, xpath_json: str, patterns_raw: str,
):
    """Extract structured data from a list of URLs."""
    from pawgrab.ai.extractor import extract_from_url
    from pawgrab.engine.extractors import get_extractor
    from pawgrab.models.extract import ExtractResponse
    from pawgrab.queue.manager import (
        append_batch_extract_result,
        get_batch_extract_webhook_url,
        update_batch_extract_job,
    )

    urls = orjson.loads(urls_json)
    browser_pool = ctx.get("browser_pool")

    schema_hint = orjson.loads(schema_hint_json) if schema_hint_json else None
    json_schema = orjson.loads(json_schema_json) if json_schema_json else None
    selectors = orjson.loads(selectors_json) if selectors_json else None
    xpath_queries = orjson.loads(xpath_json) if xpath_json else None

    await update_batch_extract_job(job_id, status=CrawlStatus.IN_PROGRESS)

    urls_extracted = 0
    job_error: str | None = None

    try:
        for url in urls:
            try:
                if strategy == "llm":
                    data = await extract_from_url(
                        url, prompt=prompt, schema_hint=schema_hint,
                        json_schema=json_schema, browser_pool=browser_pool,
                    )
                else:
                    result = await fetch_page(url, browser_pool=browser_pool)
                    extractor = get_extractor(strategy, selectors=selectors, xpath_queries=xpath_queries, patterns=patterns_raw or None)
                    data = extractor.extract(result.html)
                result_dict = ExtractResponse(success=True, url=url, data=data).model_dump()
            except Exception as exc:
                logger.warning("batch_extract_url_failed", url=url, error=str(exc))
                result_dict = {"success": False, "url": url, "error": str(exc), "data": None}

            await append_batch_extract_result(job_id, result_dict)
            urls_extracted += 1
            await update_batch_extract_job(job_id, urls_extracted=urls_extracted)

        await update_batch_extract_job(job_id, status=CrawlStatus.COMPLETED)

    except Exception as exc:
        job_error = str(exc)
        logger.error("batch_extract_job_failed", job_id=job_id, error=job_error)
        await update_batch_extract_job(job_id, status=CrawlStatus.FAILED, error=job_error)

    webhook_url = await get_batch_extract_webhook_url(job_id)
    if webhook_url:
        await send_webhook(
            webhook_url, job_id=job_id, job_type="batch_extract",
            status=CrawlStatus.COMPLETED.value if not job_error else CrawlStatus.FAILED.value,
            pages_scraped=urls_extracted, total_pages=len(urls), error=job_error,
        )


async def startup(ctx: dict):
    """Initialize worker resources — browser pool and proxy pool."""
    logger.info("worker_started")
    try:
        from pawgrab.engine.browser import BrowserPool
        pool = BrowserPool()
        await pool.start()
        ctx["browser_pool"] = pool
        logger.info("worker_browser_pool_started")
    except Exception as exc:
        logger.warning("worker_browser_pool_failed", error=str(exc))

    try:
        from pawgrab.engine.proxy_pool import ProxyPool
        proxy_pool = ProxyPool()
        await proxy_pool.start()
        ctx["proxy_pool"] = proxy_pool
        logger.info("worker_proxy_pool_started")
    except Exception as exc:
        logger.warning("worker_proxy_pool_failed", error=str(exc))


async def shutdown(ctx: dict):
    logger.info("worker_stopping")
    proxy_pool = ctx.get("proxy_pool")
    if proxy_pool:
        await proxy_pool.stop()
    pool = ctx.get("browser_pool")
    if pool:
        await pool.stop()
    from pawgrab.engine.fetcher import close_sessions
    await close_sessions()
    logger.info("worker_stopped")


class WorkerSettings:
    functions = [crawl_job, batch_scrape_job, batch_extract_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = None  # Set dynamically below
    max_jobs = settings.worker_max_jobs
    job_timeout = settings.worker_job_timeout


try:
    from arq.connections import RedisSettings
    WorkerSettings.redis_settings = RedisSettings.from_dsn(settings.redis_url)
except Exception as exc:
    logger.warning("worker_redis_settings_failed", error=str(exc), redis_url=settings.redis_url)
