"""Models for the /v1/extract endpoint."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class ExtractionStrategy(StrEnum):
    LLM = "llm"
    CSS = "css"
    XPATH = "xpath"
    REGEX = "regex"
    TABLE = "table"


class ChunkStrategy(StrEnum):
    FIXED = "fixed"
    SLIDING = "sliding"
    SEMANTIC = "semantic"


class ExtractRequest(BaseModel):
    url: HttpUrl
    prompt: str | None = Field(default=None, description="Extraction prompt (required for LLM strategy)")
    schema_hint: dict[str, Any] | None = Field(default=None, description="Example output shape to guide LLM extraction")
    json_schema: dict[str, Any] | None = Field(default=None, description="Full JSON Schema for structured output validation")
    timeout: int = Field(default=30000, ge=1000, le=120000, description="Request timeout in milliseconds")
    strategy: ExtractionStrategy = Field(default=ExtractionStrategy.LLM, description="Extraction strategy: llm, css, xpath, or regex")
    selectors: dict[str, Any] | None = Field(default=None, description="CSS selectors for CSS strategy (e.g. {'title': 'h1', 'price': '.price'})")
    xpath_queries: dict[str, str] | None = Field(default=None, description="XPath queries for XPath strategy")
    patterns: dict[str, str] | str | None = Field(default=None, description="Regex patterns for regex strategy. Dict of {field: pattern} or a single pattern with named groups")
    auto_schema: bool = Field(default=False, description="Auto-generate a JSON schema from extraction results")
    chunk_strategy: ChunkStrategy | None = Field(default=None, description="Chunking strategy for long pages: fixed, sliding, or semantic")
    chunk_size: int = Field(default=4000, ge=100, le=100000, description="Target chunk size in tokens")
    chunk_overlap: int = Field(default=200, ge=0, le=10000, description="Token overlap between chunks")
    table_index: int | None = Field(default=None, ge=0, description="Extract a specific table by index (0-based). None = extract all tables")


class ExtractResponse(BaseModel):
    success: bool
    url: str
    data: dict[str, Any] | list[dict[str, Any]] | None = None
    auto_schema: dict[str, Any] | None = None
    error: str | None = None
