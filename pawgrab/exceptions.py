"""Unified error types for the pawgrab API."""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    VALIDATION_ERROR = "validation_error"
    INVALID_API_KEY = "invalid_api_key"
    RATE_LIMITED = "rate_limited"
    ROBOTS_BLOCKED = "robots_blocked"
    RESOURCE_NOT_FOUND = "resource_not_found"
    TIMEOUT = "timeout"
    FETCH_FAILED = "fetch_failed"
    BROWSER_UNAVAILABLE = "browser_unavailable"
    QUEUE_UNAVAILABLE = "queue_unavailable"
    LLM_UNAVAILABLE = "llm_unavailable"
    EXTRACTION_FAILED = "extraction_failed"
    SEARCH_FAILED = "search_failed"
    INTERNAL_ERROR = "internal_error"


class PawgrabError(Exception):
    """Application-level error that maps to a structured JSON response."""

    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str,
        details: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)
