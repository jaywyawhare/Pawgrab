"""Models for the /v1/search endpoint."""

from pydantic import BaseModel, Field

from .common import OutputFormat
from .scrape import ScrapeResponse


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Search query")
    num_results: int = Field(default=5, ge=1, le=10, description="Number of search results to scrape")
    formats: list[OutputFormat] = Field(default=[OutputFormat.MARKDOWN], description="Output formats for scraped content")
    include_metadata: bool = Field(default=True, description="Include page metadata")


class SearchResponse(BaseModel):
    success: bool
    query: str
    results: list[ScrapeResponse] = []
    total: int = Field(default=0, description="Number of successfully scraped results")
    failed_urls: list[str] = Field(default_factory=list, description="URLs that failed to scrape")
    error: str | None = None
