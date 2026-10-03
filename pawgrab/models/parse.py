"""Models for the /v1/parse endpoint."""

from typing import Literal

from pydantic import BaseModel, Field

from .common import OutputFormat


class ParseRequest(BaseModel):
    html: str = Field(..., min_length=1, max_length=5_000_000, description="Raw HTML to parse (no fetch)")
    url: str | None = Field(default=None, max_length=2048, description="Source URL, used for metadata and relative-link resolution")
    formats: list[OutputFormat] = Field(default=[OutputFormat.MARKDOWN], description="Output formats to return")
    css_selector: str | None = Field(default=None, max_length=2000, description="CSS selector to scope content extraction to matching elements")
    excluded_tags: list[str] | None = Field(default=None, max_length=200, description="HTML tags to strip before extraction")
    excluded_selector: str | None = Field(default=None, max_length=2000, description="CSS selector for elements to remove before extraction")
    word_count_threshold: int | None = Field(default=None, ge=1, le=10000, description="Minimum words per text block to keep")
    content_filter: Literal["pruning", "bm25"] | None = Field(default=None, description="Post-extraction content filter")
    content_filter_query: str | None = Field(default=None, description="Query string for BM25 content filter")


class ParseResponse(BaseModel):
    success: bool
    markdown: str | None = None
    html: str | None = None
    text: str | None = None
    json_data: list[dict] | None = None
    csv_data: str | None = None
    xml_data: str | None = None
    title: str | None = None
    error: str | None = None
