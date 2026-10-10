"""HTTP client calls behind the MCP tools.

Each function targets a running Pawgrab API (``settings.mcp_api_url``) and
returns the parsed JSON envelope, mapping transport/HTTP errors to a plain
``{"error": ...}`` dict so an agent always gets a structured result.
"""

from __future__ import annotations

from typing import Any

import httpx

from pawgrab.config import settings

_TIMEOUT = 180.0


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.api_key:
        headers["Authorization"] = f"Bearer {settings.api_key}"
    return headers


def _base_url() -> str:
    return settings.mcp_api_url.rstrip("/")


async def _request(method: str, path: str, *, json: dict | None = None) -> dict[str, Any]:
    url = f"{_base_url()}{path}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.request(method, url, json=json, headers=_headers())
    except httpx.HTTPError as exc:
        return {"error": f"request to Pawgrab API failed: {exc}", "code": "api_unreachable"}
    try:
        body = resp.json()
    except ValueError:
        return {"error": f"non-JSON response (HTTP {resp.status_code})", "code": "bad_response"}
    if resp.status_code >= 400 and isinstance(body, dict):
        body.setdefault("error", f"HTTP {resp.status_code}")
    return body


async def scrape(
    url: str,
    formats: list[str] | None = None,
    wait_for_js: bool | None = None,
    timeout: int = 30000,
) -> dict[str, Any]:
    """Scrape a single URL and return clean markdown/html/text/json."""
    payload: dict[str, Any] = {"url": url, "timeout": timeout}
    if formats:
        payload["formats"] = formats
    if wait_for_js is not None:
        payload["wait_for_js"] = wait_for_js
    return await _request("POST", "/v1/scrape", json=payload)


async def parse(
    html: str,
    formats: list[str] | None = None,
    css_selector: str | None = None,
) -> dict[str, Any]:
    """Run raw HTML through the extraction pipeline without fetching."""
    payload: dict[str, Any] = {"html": html}
    if formats:
        payload["formats"] = formats
    if css_selector:
        payload["css_selector"] = css_selector
    return await _request("POST", "/v1/parse", json=payload)


async def extract(
    url: str,
    prompt: str | None = None,
    strategy: str = "llm",
    selectors: dict[str, Any] | None = None,
    adaptive: bool = False,
) -> dict[str, Any]:
    """Extract structured data via LLM, CSS, XPath, or regex."""
    payload: dict[str, Any] = {"url": url, "strategy": strategy, "adaptive": adaptive}
    if prompt:
        payload["prompt"] = prompt
    if selectors:
        payload["selectors"] = selectors
    return await _request("POST", "/v1/extract", json=payload)


async def search(
    query: str,
    num_results: int = 5,
    exclude_domains: list[str] | None = None,
) -> dict[str, Any]:
    """Search the web and scrape each result."""
    payload: dict[str, Any] = {"query": query, "num_results": num_results}
    if exclude_domains:
        payload["exclude_domains"] = exclude_domains
    return await _request("POST", "/v1/search", json=payload)


async def map_site(url: str, limit: int = 100) -> dict[str, Any]:
    """Discover URLs for a site via its sitemap or a shallow crawl."""
    return await _request("POST", "/v1/map", json={"url": url, "limit": limit})


async def crawl(url: str, max_pages: int = 10, max_depth: int = 2) -> dict[str, Any]:
    """Start an async crawl job. Returns a job id to poll with crawl_status."""
    return await _request(
        "POST",
        "/v1/crawl",
        json={"url": url, "max_pages": max_pages, "max_depth": max_depth},
    )


async def crawl_status(job_id: str) -> dict[str, Any]:
    """Get the status and results of a crawl job."""
    return await _request("GET", f"/v1/crawl/{job_id}")
