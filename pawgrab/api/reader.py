"""Structured readers: /v1/transcript (YouTube), /v1/feed (RSS/Atom), /v1/read (auto-route)."""

import structlog
from fastapi import APIRouter

from pawgrab.engine.feed import fetch_feed
from pawgrab.engine.github import fetch_repo
from pawgrab.engine.platform import detect_platform
from pawgrab.engine.reddit import fetch_reddit
from pawgrab.engine.transcript import fetch_transcript
from pawgrab.exceptions import ErrorCode, PawgrabError
from pawgrab.models.reader import (
    FeedRequest,
    FeedResponse,
    GithubRequest,
    GithubResponse,
    ReadRequest,
    ReadResponse,
    RedditRequest,
    RedditResponse,
    TranscriptRequest,
    TranscriptResponse,
)
from pawgrab.utils.url_safety import SSRFError

logger = structlog.get_logger()
router = APIRouter(tags=["Reader"])


def _ssrf_guard(exc: Exception) -> None:
    """Re-raise SSRF as a 400; leave other errors for the caller's soft-fail path."""
    if isinstance(exc, SSRFError):
        raise PawgrabError(
            status_code=400,
            code=ErrorCode.VALIDATION_ERROR,
            message="URL blocked: target resolves to a private/internal address",
        ) from None


async def _transcript(req: TranscriptRequest) -> TranscriptResponse:
    try:
        data = await fetch_transcript(req.url, languages=req.languages)
        return TranscriptResponse(success=True, **data)
    except Exception as exc:
        _ssrf_guard(exc)
        logger.info("transcript_failed", url=req.url, error=str(exc))
        return TranscriptResponse(success=False, error=str(exc))


async def _feed(req: FeedRequest) -> FeedResponse:
    try:
        data = await fetch_feed(req.url, limit=req.limit)
        return FeedResponse(success=True, **data)
    except Exception as exc:
        _ssrf_guard(exc)
        logger.info("feed_failed", url=req.url, error=str(exc))
        return FeedResponse(success=False, error=str(exc))


async def _reddit(req: RedditRequest) -> RedditResponse:
    try:
        data = await fetch_reddit(req.url, limit=req.limit)
        return RedditResponse(success=True, **data)
    except Exception as exc:
        _ssrf_guard(exc)
        logger.info("reddit_failed", url=req.url, error=str(exc))
        return RedditResponse(success=False, error=str(exc))


async def _github(req: GithubRequest) -> GithubResponse:
    try:
        data = await fetch_repo(req.url)
        return GithubResponse(success=True, **data)
    except Exception as exc:
        _ssrf_guard(exc)
        logger.info("github_failed", url=req.url, error=str(exc))
        return GithubResponse(success=False, error=str(exc))


@router.post("/transcript", response_model=TranscriptResponse)
async def transcript(req: TranscriptRequest):
    """Extract a YouTube video's caption track as structured, timestamped segments."""
    return await _transcript(req)


@router.post("/feed", response_model=FeedResponse)
async def feed(req: FeedRequest):
    """Parse an RSS 2.0 or Atom feed into structured items."""
    return await _feed(req)


@router.post("/reddit", response_model=RedditResponse)
async def reddit(req: RedditRequest):
    """Read a Reddit post (with comments) or listing via the public JSON endpoint (no login)."""
    return await _reddit(req)


@router.post("/github", response_model=GithubResponse)
async def github(req: GithubRequest):
    """Read GitHub repository metadata via the public REST API (no token)."""
    return await _github(req)


@router.post("/read", response_model=ReadResponse)
async def read(req: ReadRequest):
    """Auto-detect the URL's platform and route to the transcript, feed, or scrape reader."""
    kind = detect_platform(req.url)
    if kind == "youtube":
        sub = await _transcript(TranscriptRequest(url=req.url, languages=req.languages))
        return ReadResponse(success=sub.success, kind=kind, url=req.url, transcript=sub, error=sub.error)
    if kind == "reddit":
        sub = await _reddit(RedditRequest(url=req.url, limit=min(req.limit, 100)))
        return ReadResponse(success=sub.success, kind=kind, url=req.url, reddit=sub, error=sub.error)
    if kind == "github":
        sub = await _github(GithubRequest(url=req.url))
        return ReadResponse(success=sub.success, kind=kind, url=req.url, github=sub, error=sub.error)
    if kind == "feed":
        sub = await _feed(FeedRequest(url=req.url, limit=req.limit))
        return ReadResponse(success=sub.success, kind=kind, url=req.url, feed=sub, error=sub.error)

    from pawgrab.dependencies import try_browser_pool, try_proxy_pool
    from pawgrab.engine.scrape_service import scrape_url
    from pawgrab.models.scrape import ScrapeResponse

    try:
        scraped: ScrapeResponse = await scrape_url(
            req.url,
            formats=req.formats,
            browser_pool=await try_browser_pool(),
            proxy_pool=await try_proxy_pool(),
        )
        return ReadResponse(success=True, kind=kind, url=req.url, scrape=scraped)
    except SSRFError:
        _ssrf_guard(SSRFError())
    except Exception as exc:
        logger.info("read_scrape_failed", url=req.url, error=str(exc))
        return ReadResponse(success=False, kind=kind, url=req.url, error=str(exc))
