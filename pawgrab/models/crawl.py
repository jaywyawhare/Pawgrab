"""Models for the /v1/crawl endpoint."""

from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl, field_validator

from .common import JobStatus, OutputFormat, PaginatedJobResult
from .scrape import ScrapeResponse

CrawlStatus = JobStatus


class CrawlStrategyType(StrEnum):
    BFS = "bfs"
    DFS = "dfs"
    BEST_FIRST = "best_first"


class CrawlParamsBase(BaseModel):
    """Shared crawl/schedule parameters."""

    url: HttpUrl
    max_pages: int = Field(default=10, ge=1, le=500, description="Maximum number of pages to crawl")
    max_depth: int = Field(default=3, ge=1, le=10, description="Maximum link depth from the start URL")
    formats: list[OutputFormat] = Field(default=[OutputFormat.MARKDOWN], description="Output formats for scraped content")
    webhook_url: HttpUrl | None = Field(default=None, description="URL to POST results to when job completes")
    strategy: CrawlStrategyType = Field(default=CrawlStrategyType.BFS, description="Crawl strategy: bfs, dfs, or best_first")


class CrawlRequest(CrawlParamsBase):
    include_metadata: bool = Field(default=True, description="Include page metadata (title, description, language)")
    resume_job_id: str | None = Field(default=None, description="Job ID of a previous crawl to resume")
    allowed_domains: list[str] | None = Field(default=None, max_length=200, description="Only follow links to these domains")
    blocked_domains: list[str] | None = Field(default=None, max_length=200, description="Never follow links to these domains")
    include_path_patterns: list[str] | None = Field(default=None, max_length=50, description="Only follow URLs matching these regex patterns")
    exclude_path_patterns: list[str] | None = Field(default=None, max_length=50, description="Skip URLs matching these regex patterns")
    keywords: list[str] | None = Field(default=None, max_length=200, description="Keywords for best_first strategy scoring")

    @field_validator("include_path_patterns", "exclude_path_patterns")
    @classmethod
    def _bound_pattern_length(cls, v: list[str] | None) -> list[str] | None:

        if v and any(len(p) > 500 for p in v):
            raise ValueError("path pattern exceeds 500 characters")
        return v


class CrawlResponse(BaseModel):
    job_id: str
    status: JobStatus
    url: str


class CrawlJobStatus(PaginatedJobResult):
    pages_scraped: int = Field(default=0, description="Number of pages successfully scraped so far")
    total_pages: int | None = Field(default=None, description="Estimated total pages (known after sitemap discovery)")
    results: list[ScrapeResponse] = []
