"""Browser-enabled Pawgrab adapter for scrape-evals (Patchright fallback on).

Same wiring as `pawgrab_scraper.py` but builds one shared BrowserPool so JS-heavy
pages escalate from curl_cffi to a real headless browser.

Measured caveat (2026-07, datasets/1-0-0.csv): on this dataset the browser path
*regressed* the hard tail — of 82 pages curl flagged "needs JS" it rescued only
~16%, and ~34% flipped from a soft block to a hard 403 because headless Chromium
is more fingerprintable than curl_cffi's TLS impersonation. Keep this engine for
JS-empty pages that are NOT anti-bot protected; do not use it to brute-force 403s.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from .base import Scraper, ScrapeResult


class PawgrabBrowserScraper(Scraper):
    _pool = None
    _lock = asyncio.Lock()

    def check_environment(self) -> bool:
        try:
            from pawgrab.engine.browser import BrowserPool  # noqa: F401

            return True
        except Exception:
            return False

    async def _get_pool(self):
        if PawgrabBrowserScraper._pool is None:
            async with PawgrabBrowserScraper._lock:
                if PawgrabBrowserScraper._pool is None:
                    from pawgrab.engine.browser import BrowserPool

                    pool = BrowserPool(pool_size=4)
                    await pool.start()
                    PawgrabBrowserScraper._pool = pool
        return PawgrabBrowserScraper._pool

    async def scrape(self, url: str, run_id: str) -> ScrapeResult:
        from pawgrab.engine.scrape_service import scrape_url
        from pawgrab.models.common import OutputFormat

        created_at = datetime.now().isoformat()
        try:
            pool = await self._get_pool()
            resp = await scrape_url(
                url,
                formats=[OutputFormat.MARKDOWN],
                browser_pool=pool,
                proxy_pool=None,
                wait_for_js=None,
                timeout=45_000,
            )
            content = resp.markdown or ""
            status_code = resp.metadata.status_code if resp.metadata else (200 if resp.success else 502)
            error = resp.error if not resp.success else None
            return ScrapeResult(
                run_id=run_id,
                scraper="pawgrab_browser_scraper",
                url=url,
                status_code=status_code,
                error=error,
                content_size=len(content.encode("utf-8")) if content else 0,
                format="markdown",
                created_at=created_at,
                content=content or None,
            )
        except Exception as e:
            return ScrapeResult(
                run_id=run_id,
                scraper="pawgrab_browser_scraper",
                url=url,
                status_code=500,
                error=f"{type(e).__name__}: {str(e)}",
                content_size=0,
                format="markdown",
                created_at=datetime.now().isoformat(),
                content=None,
            )
