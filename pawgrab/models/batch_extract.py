"""Models for the /v1/batch/extract endpoint."""

from pydantic import BaseModel, Field, HttpUrl

from .common import AsyncJobResponse, PaginatedJobResult
from .extract import ExtractResponse, ExtractionStrategy


class BatchExtractRequest(BaseModel):
    urls: list[HttpUrl] = Field(..., min_length=1, max_length=100, description="URLs to extract from (1-100)")
    prompt: str | None = Field(default=None, description="Extraction prompt (required for LLM strategy)")
    strategy: ExtractionStrategy = Field(default=ExtractionStrategy.LLM, description="Extraction strategy")
    schema_hint: dict | None = Field(default=None, description="Example output shape")
    json_schema: dict | None = Field(default=None, description="Full JSON Schema for validation")
    selectors: dict | None = Field(default=None, description="CSS selectors for CSS strategy")
    xpath_queries: dict[str, str] | None = Field(default=None, description="XPath queries")
    patterns: dict[str, str] | str | None = Field(default=None, description="Regex patterns")
    webhook_url: HttpUrl | None = Field(default=None, description="Webhook URL for completion notification")


class BatchExtractResponse(AsyncJobResponse):
    pass


class BatchExtractJobStatus(PaginatedJobResult):
    urls_extracted: int = Field(default=0, description="URLs extracted so far")
    total_urls: int = Field(default=0, description="Total URLs in batch")
    results: list[ExtractResponse] = []
