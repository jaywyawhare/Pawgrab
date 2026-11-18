"""Models for the content index ("Alexandria-lite", F4)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class IndexEntry(BaseModel):
    url: str
    title: str = ""
    word_count: int = 0
    fetched_at: int = 0
    markdown_hash: str = ""


class IndexSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    k: int = Field(default=10, ge=1, le=100)
    include_content: bool = Field(default=False, description="Return the cached markdown with each hit")


class IndexHit(IndexEntry):
    score: float = 0.0
    markdown: str | None = None


class IndexSearchResponse(BaseModel):
    success: bool = True
    query: str
    hits: list[IndexHit] = Field(default_factory=list)
    total: int = 0


class IndexStats(BaseModel):
    success: bool = True
    enabled: bool
    entries: int = 0
    store: str = ""
