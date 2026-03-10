"""Models for the /v1/extract endpoint."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class ExtractionStrategy(str, Enum):
    LLM = "llm"
    CSS = "css"
    XPATH = "xpath"
    REGEX = "regex"


class ExtractRequest(BaseModel):
    url: HttpUrl
    prompt: str = ""  # required for LLM strategy, optional for others
    schema_hint: dict[str, Any] | None = None
    # Full JSON schema for structured output validation (uses OpenAI structured outputs)
    json_schema: dict[str, Any] | None = None
    timeout: int = Field(default=30000, ge=1000, le=120000)
    # Extraction strategy
    strategy: ExtractionStrategy = ExtractionStrategy.LLM
    # CSS strategy config
    selectors: dict[str, Any] | None = None
    # XPath strategy config
    xpath_queries: dict[str, str] | None = None
    # Regex strategy config
    patterns: dict[str, str] | str | None = None
    # Auto-generate schema from extraction results
    auto_schema: bool = False
    # Chunking config for LLM strategy
    chunk_strategy: str | None = None  # "fixed", "sliding", "semantic"
    chunk_size: int = Field(default=4000, ge=100, le=100000)
    chunk_overlap: int = Field(default=200, ge=0, le=10000)


class ExtractResponse(BaseModel):
    success: bool
    url: str
    data: dict[str, Any] | list[dict[str, Any]] | None = None
    auto_schema: dict[str, Any] | None = None
    error: str | None = None
