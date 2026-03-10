"""Models for the /v1/crawl endpoint."""

from enum import Enum

from pydantic import BaseModel, Field, HttpUrl

from .common import OutputFormat
from .scrape import ScrapeResponse


class CrawlStatus(str, Enum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class CrawlStrategyType(str, Enum):
    BFS = "bfs"
    DFS = "dfs"
    BEST_FIRST = "best_first"


class CrawlRequest(BaseModel):
    url: HttpUrl
    max_pages: int = Field(default=10, ge=1, le=500)
    max_depth: int = Field(default=3, ge=1, le=10)
    formats: list[OutputFormat] = [OutputFormat.MARKDOWN]
    include_metadata: bool = True
    webhook_url: HttpUrl | None = None
    # Resume a previously failed/crashed crawl from its checkpoint
    resume_job_id: str | None = None
    # Crawl strategy
    strategy: CrawlStrategyType = CrawlStrategyType.BFS
    # URL filtering
    allowed_domains: list[str] | None = None
    blocked_domains: list[str] | None = None
    include_path_patterns: list[str] | None = None
    exclude_path_patterns: list[str] | None = None
    # BestFirst scoring keywords
    keywords: list[str] | None = None


class CrawlResponse(BaseModel):
    job_id: str
    status: CrawlStatus
    url: str


class CrawlJobStatus(BaseModel):
    job_id: str
    status: CrawlStatus
    pages_scraped: int = 0
    total_pages: int | None = None
    results: list[ScrapeResponse] = []
    error: str | None = None
