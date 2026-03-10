"""Shared models and enums."""

from enum import Enum

from pydantic import BaseModel


class OutputFormat(str, Enum):
    MARKDOWN = "markdown"
    HTML = "html"
    TEXT = "text"
    JSON = "json"
    CSV = "csv"
    XML = "xml"


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    detail: str | None = None
