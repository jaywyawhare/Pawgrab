"""Web search providers for the /v1/search endpoint."""

from __future__ import annotations

import structlog
from curl_cffi.requests import AsyncSession

from pawgrab.config import settings

logger = structlog.get_logger()


async def search_web(query: str, num_results: int = 5) -> list[str]:
    """Search the web and return a list of URLs.

    Dispatches to configured provider (duckduckgo, serpapi, google).
    """
    provider = settings.search_provider
    if provider == "serpapi" and settings.serpapi_key:
        return await _search_serpapi(query, num_results)
    elif provider == "google" and settings.google_search_api_key:
        return await _search_google(query, num_results)
    else:
        return await _search_duckduckgo(query, num_results)


async def _search_duckduckgo(query: str, num_results: int) -> list[str]:
    """Search using duckduckgo-search library."""
    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=num_results))
        return [r["href"] for r in results if r.get("href")]
    except Exception as exc:
        logger.warning("duckduckgo_search_failed", error=str(exc))
        return []


async def _search_serpapi(query: str, num_results: int) -> list[str]:
    """Search using SerpAPI."""
    try:
        async with AsyncSession() as session:
            resp = await session.get(
                "https://serpapi.com/search",
                params={
                    "q": query,
                    "api_key": settings.serpapi_key,
                    "num": num_results,
                    "engine": "google",
                },
                timeout=15,
            )
        data = resp.json()
        return [r["link"] for r in data.get("organic_results", []) if r.get("link")]
    except Exception as exc:
        logger.warning("serpapi_search_failed", error=str(exc))
        return []


async def _search_google(query: str, num_results: int) -> list[str]:
    """Search using Google Custom Search JSON API."""
    try:
        async with AsyncSession() as session:
            resp = await session.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "q": query,
                    "key": settings.google_search_api_key,
                    "cx": settings.google_search_cx,
                    "num": num_results,
                },
                timeout=15,
            )
        data = resp.json()
        return [item["link"] for item in data.get("items", []) if item.get("link")]
    except Exception as exc:
        logger.warning("google_search_failed", error=str(exc))
        return []
