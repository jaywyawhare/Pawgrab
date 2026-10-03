"""Models for the /v1/search endpoint."""

from typing import Literal

from pydantic import BaseModel, Field

from .common import OutputFormat
from .scrape import ScrapeResponse


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Search query")
    num_results: int = Field(default=5, ge=1, le=10, description="Number of search results to scrape")
    formats: list[OutputFormat] = Field(default=[OutputFormat.MARKDOWN], description="Output formats for scraped content")
    include_metadata: bool = Field(default=True, description="Include page metadata")

    page: int = Field(default=1, ge=1, le=20, description="Result page number")
    time_range: Literal["day", "week", "month", "year"] | None = Field(default=None, description="Restrict results to a recent time window")
    safesearch: Literal[0, 1, 2] = Field(default=0, description="0=off, 1=moderate, 2=strict")
    region: str = Field(default="us-en", max_length=10, description="Region/locale, e.g. 'us-en', 'uk-en'")
    category: Literal["general", "news", "images", "videos"] = Field(default="general", description="Result category")
    include_domains: list[str] | None = Field(default=None, max_length=50, description="Only keep results from these domains (e.g. ['example.com'] includes subdomains)")
    exclude_domains: list[str] | None = Field(default=None, max_length=50, description="Drop results from these domains (e.g. ['pinterest.com'])")
    scrape: bool = Field(default=True, description="Scrape each result; if false, return SERP metadata only")


class SearchResponse(BaseModel):
    success: bool
    query: str
    results: list[ScrapeResponse] = []
    total: int = Field(default=0, description="Number of successfully scraped results")
    failed_urls: list[str] = Field(default_factory=list, description="URLs that failed to scrape")

    search_results: list[dict] = Field(default_factory=list, description="Ranked SERP items (position/title/link/snippet/type/engines/score)")
    answers: list[str] = Field(default_factory=list, description="Instant answers (calculator, definitions, etc.)")
    infoboxes: list[dict] = Field(default_factory=list, description="Knowledge/abstract infoboxes")
    suggestions: list[str] = Field(default_factory=list, description="Related-search suggestions")
    corrections: list[str] = Field(default_factory=list, description="Spelling corrections / did-you-mean")
    unresponsive_engines: list[str] = Field(default_factory=list, description="Engines that returned nothing")
    timings: list[dict] = Field(default_factory=list, description="Per-engine latency (ms)")
    page: int = Field(default=1, description="Result page number")
    error: str | None = None
