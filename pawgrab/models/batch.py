"""Models for the /v1/batch/scrape endpoint."""

from pydantic import BaseModel, Field, HttpUrl

from .common import OutputFormat
from .scrape import ScrapeResponse


class BatchScrapeRequest(BaseModel):
    urls: list[HttpUrl] = Field(..., min_length=1, max_length=100)
    formats: list[OutputFormat] = [OutputFormat.MARKDOWN]
    include_metadata: bool = True
    wait_for_js: bool | None = None
    webhook_url: HttpUrl | None = None


class BatchScrapeResponse(BaseModel):
    job_id: str
    status: str
    total_urls: int


class BatchJobStatus(BaseModel):
    job_id: str
    status: str
    urls_scraped: int = 0
    total_urls: int = 0
    results: list[dict] = []
    error: str | None = None
