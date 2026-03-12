"""Models for the /v1/batch/scrape endpoint."""

from pydantic import BaseModel, Field, HttpUrl

from .common import JobStatus, OutputFormat
from .scrape import ScrapeResponse


class BatchScrapeRequest(BaseModel):
    urls: list[HttpUrl] = Field(..., min_length=1, max_length=100, description="URLs to scrape (1-100)")
    formats: list[OutputFormat] = Field(default=[OutputFormat.MARKDOWN], description="Output formats for scraped content")
    include_metadata: bool = Field(default=True, description="Include page metadata (title, description, language)")
    wait_for_js: bool | None = Field(default=None, description="Force JS rendering (None = auto-detect)")
    webhook_url: HttpUrl | None = Field(default=None, description="URL to POST results to when batch completes")


class BatchScrapeResponse(BaseModel):
    job_id: str
    status: JobStatus
    total_urls: int


class BatchJobStatus(BaseModel):
    job_id: str
    status: JobStatus
    urls_scraped: int = Field(default=0, description="Number of URLs successfully scraped so far")
    total_urls: int = Field(default=0, description="Total number of URLs in the batch")
    results: list[ScrapeResponse] = []
    error: str | None = None
    page: int | None = Field(default=None, description="Current results page number")
    limit: int | None = Field(default=None, description="Results per page")
    total_results: int | None = Field(default=None, description="Total number of result entries stored")
    has_next: bool | None = Field(default=None, description="Whether more result pages are available")
