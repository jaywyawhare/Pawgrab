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


class AsyncJobResponse(BaseModel):
    """Immediate response returned when an async job is accepted (202)."""

    job_id: str
    status: JobStatus
    total_urls: int


class PaginatedJobResult(BaseModel):
    """Base for paginated async job results."""

    job_id: str
    status: JobStatus
    results: list = []
    error: str | None = None
    page: int | None = Field(default=None, description="Current results page number")
    limit: int | None = Field(default=None, description="Results per page")
    total_results: int | None = Field(default=None, description="Total number of result entries stored")
    has_next: bool | None = Field(default=None, description="Whether more result pages are available")


class ErrorResponse(BaseModel):
    """Standard error response returned by all endpoints."""

    success: bool = False
    error: str = Field(description="Human-readable error message")
    code: str | None = Field(default=None, description="Machine-readable error code")
    details: str | None = Field(default=None, description="Additional context about the error")
    request_id: str | None = Field(default=None, description="Request ID for support correlation")


JOB_ID_RESPONSES = {
    400: {"model": ErrorResponse, "description": "Invalid job ID format"},
    404: {"model": ErrorResponse, "description": "Job not found"},
}

QUEUE_RESPONSES = {
    429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    503: {"model": ErrorResponse, "description": "Queue service unavailable"},
}
