"""Models for the /v1/map endpoint."""

from pydantic import BaseModel, Field, HttpUrl


class MapRequest(BaseModel):
    url: HttpUrl
    include_subdomains: bool = Field(default=False, description="Include URLs from subdomains")
    limit: int = Field(default=5000, ge=1, le=10000, description="Maximum number of URLs to return")


class MapResponse(BaseModel):
    success: bool
    url: str
    urls: list[str] = []
    total: int = Field(default=0, description="Number of discovered URLs")
    source: str = Field(default="", description="Discovery method used (sitemap, html_links, etc.)")
    error: str | None = None
