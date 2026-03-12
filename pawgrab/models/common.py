"""Shared models and enums."""

from enum import Enum

from pydantic import BaseModel, Field


class OutputFormat(str, Enum):
    MARKDOWN = "markdown"
    HTML = "html"
    TEXT = "text"
    JSON = "json"
    CSV = "csv"
    XML = "xml"


class JobStatus(str, Enum):
    """Status for async jobs (crawl, batch)."""

    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class ErrorResponse(BaseModel):
    """Standard error response returned by all endpoints."""

    success: bool = False
    error: str = Field(description="Human-readable error message")
    code: str | None = Field(default=None, description="Machine-readable error code")
    details: str | None = Field(
        default=None, description="Additional context about the error"
    )
    request_id: str | None = Field(
        default=None, description="Request ID for support correlation"
    )
