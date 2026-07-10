"""Pawgrab engine adapter for the external `scrape-evals` benchmark.

Drop this file into a checkout of https://github.com/martynasoxylabs/scrape-evals
under `engines/` and run:

    PAWGRAB_RESPECT_ROBOTS=false \
    python run_eval.py --scrape_engine pawgrab_scraper \
        --dataset datasets/1-0-0.csv --output-dir runs/pawgrab --max-workers 24 --rerun

It drives Pawgrab's library scrape pipeline directly (curl_cffi fetch, no browser
pool) and returns Markdown so the quality analyzer grades article content rather
than raw HTML boilerplate.

Note: the other engines in scrape-evals ignore robots.txt, so set
PAWGRAB_RESPECT_ROBOTS=false for an apples-to-apples coverage comparison.
"""

from __future__ import annotations

from datetime import datetime

from .base import ScrapeResult, Scraper


class PawgrabScraper(Scraper):
    def check_environment(self) -> bool:
        try:
            from pawgrab.engine.scrape_service import scrape_url  # noqa: F401

            return True
        except Exception:
            return False

    async def scrape(self, url: str, run_id: str) -> ScrapeResult:
        from pawgrab.engine.scrape_service import scrape_url
        from pawgrab.models.common import OutputFormat

        created_at = datetime.now().isoformat()
        try:
            resp = await scrape_url(
                url,
                formats=[OutputFormat.MARKDOWN],
                browser_pool=None,
                proxy_pool=None,
                wait_for_js=None,
                timeout=30_000,
            )
            content = resp.markdown or ""
            status_code = resp.metadata.status_code if resp.metadata else (200 if resp.success else 502)
            error = resp.error if not resp.success else None
            return ScrapeResult(
                run_id=run_id,
                scraper="pawgrab_scraper",
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
                scraper="pawgrab_scraper",
                url=url,
                status_code=500,
                error=f"{type(e).__name__}: {str(e)}",
                content_size=0,
                format="markdown",
                created_at=datetime.now().isoformat(),
                content=None,
            )
