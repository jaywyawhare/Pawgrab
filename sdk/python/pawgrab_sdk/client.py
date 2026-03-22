"""Pawgrab API client."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from pawgrab_sdk.models import (
    CrawlJob,
    CrawlOptions,
    CrawlStatus,
    ExtractOptions,
    ExtractResponse,
    ScrapeOptions,
    ScrapeResponse,
    SearchOptions,
)


class PawgrabError(Exception):
    """Error from the Pawgrab API."""

    def __init__(self, status_code: int, message: str, code: str | None = None, details: str | None = None):
        self.status_code = status_code
        self.message = message
        self.code = code
        self.details = details
        super().__init__(f"[{status_code}] {message}")


class PawgrabClient:
    """Async/sync client for the Pawgrab web scraping API.

    Usage::

        # Async
        async with PawgrabClient("http://localhost:8000") as client:
            result = await client.scrape("https://example.com")

        # Sync
        client = PawgrabClient("http://localhost:8000")
        result = client.scrape_sync("https://example.com")
    """

    def __init__(self, base_url: str = "http://localhost:8000", api_key: str | None = None, timeout: float = 120.0):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._sync_client: httpx.Client | None = None

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers(),
                timeout=self._timeout,
            )
        return self._client

    def _get_sync_client(self) -> httpx.Client:
        if self._sync_client is None:
            self._sync_client = httpx.Client(
                base_url=self._base_url,
                headers=self._headers(),
                timeout=self._timeout,
            )
        return self._sync_client

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._sync_client:
            self._sync_client.close()
            self._sync_client = None

    def _check(self, resp: httpx.Response) -> dict:
        if resp.status_code >= 400:
            try:
                body = resp.json()
                raise PawgrabError(
                    resp.status_code,
                    body.get("error", resp.text),
                    code=body.get("code"),
                    details=body.get("details"),
                )
            except (ValueError, KeyError):
                raise PawgrabError(resp.status_code, resp.text)
        return resp.json()

    async def scrape(self, url: str, options: ScrapeOptions | None = None) -> ScrapeResponse:
        """Scrape a single URL."""
        client = await self._get_client()
        body = {"url": url}
        if options:
            body.update(options.to_dict())
        resp = await client.post("/v1/scrape", json=body)
        return ScrapeResponse.from_dict(self._check(resp))

    def scrape_sync(self, url: str, options: ScrapeOptions | None = None) -> ScrapeResponse:
        """Scrape a single URL (synchronous)."""
        client = self._get_sync_client()
        body = {"url": url}
        if options:
            body.update(options.to_dict())
        resp = client.post("/v1/scrape", json=body)
        return ScrapeResponse.from_dict(self._check(resp))

    async def extract(self, url: str, options: ExtractOptions | None = None) -> ExtractResponse:
        """Extract structured data from a URL."""
        client = await self._get_client()
        body = {"url": url}
        if options:
            body.update(options.to_dict())
        resp = await client.post("/v1/extract", json=body)
        return ExtractResponse.from_dict(self._check(resp))

    def extract_sync(self, url: str, options: ExtractOptions | None = None) -> ExtractResponse:
        client = self._get_sync_client()
        body = {"url": url}
        if options:
            body.update(options.to_dict())
        resp = client.post("/v1/extract", json=body)
        return ExtractResponse.from_dict(self._check(resp))

    async def search(self, query: str, options: SearchOptions | None = None) -> dict:
        """Search the web and scrape results."""
        client = await self._get_client()
        body: dict[str, Any] = {"query": query}
        if options:
            body.update(options.to_dict())
        resp = await client.post("/v1/search", json=body)
        return self._check(resp)

    def search_sync(self, query: str, options: SearchOptions | None = None) -> dict:
        client = self._get_sync_client()
        body: dict[str, Any] = {"query": query}
        if options:
            body.update(options.to_dict())
        resp = client.post("/v1/search", json=body)
        return self._check(resp)

    async def crawl(self, url: str, options: CrawlOptions | None = None) -> CrawlJob:
        """Start an async crawl job."""
        client = await self._get_client()
        body = {"url": url}
        if options:
            body.update(options.to_dict())
        resp = await client.post("/v1/crawl", json=body)
        return CrawlJob.from_dict(self._check(resp))

    async def get_crawl_status(self, job_id: str, page: int = 1, limit: int = 50) -> CrawlStatus:
        """Get crawl job status and results."""
        client = await self._get_client()
        resp = await client.get(f"/v1/crawl/{job_id}", params={"page": page, "limit": limit})
        return CrawlStatus.from_dict(self._check(resp))

    async def wait_for_crawl(self, job_id: str, poll_interval: float = 2.0, timeout: float = 600.0) -> CrawlStatus:
        """Poll until crawl completes or times out."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = await self.get_crawl_status(job_id)
            if status.status in ("completed", "failed"):
                return status
            await asyncio.sleep(poll_interval)
        raise TimeoutError(f"Crawl {job_id} did not complete within {timeout}s")

    def crawl_sync(self, url: str, options: CrawlOptions | None = None) -> CrawlJob:
        client = self._get_sync_client()
        body = {"url": url}
        if options:
            body.update(options.to_dict())
        resp = client.post("/v1/crawl", json=body)
        return CrawlJob.from_dict(self._check(resp))

    async def batch_scrape(self, urls: list[str], formats: list[str] | None = None) -> dict:
        """Start a batch scrape job."""
        client = await self._get_client()
        body: dict[str, Any] = {"urls": urls}
        if formats:
            body["formats"] = formats
        resp = await client.post("/v1/batch/scrape", json=body)
        return self._check(resp)

    async def batch_extract(self, urls: list[str], prompt: str | None = None, strategy: str = "llm") -> dict:
        """Start a batch extract job."""
        client = await self._get_client()
        body: dict[str, Any] = {"urls": urls, "strategy": strategy}
        if prompt:
            body["prompt"] = prompt
        resp = await client.post("/v1/batch/extract", json=body)
        return self._check(resp)

    async def get_batch_status(self, job_id: str, page: int = 1, limit: int = 50) -> dict:
        """Get batch job status."""
        client = await self._get_client()
        resp = await client.get(f"/v1/batch/{job_id}", params={"page": page, "limit": limit})
        return self._check(resp)

    async def create_session(self, ttl: int = 3600, cookies: dict | None = None) -> str:
        """Create a persistent session. Returns session ID."""
        client = await self._get_client()
        body: dict[str, Any] = {"ttl": ttl}
        if cookies:
            body["cookies"] = cookies
        resp = await client.post("/v1/session", json=body)
        return self._check(resp)["session_id"]

    async def get_session(self, session_id: str) -> dict:
        client = await self._get_client()
        resp = await client.get(f"/v1/session/{session_id}")
        return self._check(resp)

    async def delete_session(self, session_id: str) -> dict:
        client = await self._get_client()
        resp = await client.delete(f"/v1/session/{session_id}")
        return self._check(resp)

    async def create_schedule(self, url: str, cron: str, **kwargs) -> dict:
        """Create a scheduled crawl."""
        client = await self._get_client()
        body = {"url": url, "cron": cron, **kwargs}
        resp = await client.post("/v1/schedule", json=body)
        return self._check(resp)

    async def list_schedules(self) -> dict:
        client = await self._get_client()
        resp = await client.get("/v1/schedules")
        return self._check(resp)

    async def delete_schedule(self, schedule_id: str) -> dict:
        client = await self._get_client()
        resp = await client.delete(f"/v1/schedule/{schedule_id}")
        return self._check(resp)

    async def health(self) -> dict:
        client = await self._get_client()
        resp = await client.get("/health")
        return self._check(resp)

    async def metrics(self) -> dict:
        client = await self._get_client()
        resp = await client.get("/v1/metrics")
        return self._check(resp)

    async def map(self, url: str) -> dict:
        """Discover URLs on a site via sitemap."""
        client = await self._get_client()
        resp = await client.post("/v1/map", json={"url": url})
        return self._check(resp)
