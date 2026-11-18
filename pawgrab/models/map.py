"""Models for the /map endpoint."""

from pydantic import BaseModel, Field, HttpUrl


class MapRequest(BaseModel):
    url: HttpUrl
    include_subdomains: bool = Field(default=False, description="Include URLs from subdomains")
    limit: int = Field(default=5000, ge=1, le=10000, description="Maximum number of URLs to return")
    search: str | None = Field(default=None, description="Rank discovered URLs by relevance to this query")


class MapResponse(BaseModel):
    success: bool
    url: str
    urls: list[str] = []
    scores: list[float] | None = Field(default=None, description="Relevance scores aligned to `urls`, present only when `search` is given")
    total: int = Field(default=0, description="Number of discovered URLs")
    source: str = Field(default="", description="Discovery method used (sitemap, html_links, etc.)")
    error: str | None = None
