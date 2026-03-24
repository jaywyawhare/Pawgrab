"""Unified error types for the pawgrab API."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
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

    @classmethod
    def not_found(cls, resource: str) -> PawgrabError:
        return cls(404, ErrorCode.RESOURCE_NOT_FOUND, f"Job not found: {resource}")

    @classmethod
    def queue_unavailable(cls) -> PawgrabError:
        return cls(503, ErrorCode.QUEUE_UNAVAILABLE, "Queue service unavailable — is Redis running?")

    @classmethod
    def timeout(cls, timeout_ms: int) -> PawgrabError:
        return cls(504, ErrorCode.TIMEOUT, f"Request timed out after {timeout_ms}ms")

    @classmethod
    def fetch_failed(cls, exc: Exception) -> PawgrabError:
        return cls(502, ErrorCode.FETCH_FAILED, f"Failed to fetch URL: {type(exc).__name__}")

    @classmethod
    def invalid_job_id(cls) -> PawgrabError:
        return cls(400, ErrorCode.VALIDATION_ERROR, "Invalid job ID format — must be a 12-character hex string")
