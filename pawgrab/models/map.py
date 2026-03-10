"""Models for the /v1/map endpoint."""

from pydantic import BaseModel, Field, HttpUrl


class MapRequest(BaseModel):
    url: HttpUrl
    include_subdomains: bool = False
    limit: int = Field(default=5000, ge=1, le=10000)


class MapResponse(BaseModel):
    success: bool
    url: str
    urls: list[str] = []
    total: int = 0
    source: str = ""
    error: str | None = None
