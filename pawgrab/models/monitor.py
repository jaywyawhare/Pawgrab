"""Models for change tracking / content monitoring."""

from enum import StrEnum

from pydantic import BaseModel


class ChangeType(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"


class ContentDiff(BaseModel):
    change_type: ChangeType
    previous_hash: str | None = None
    current_hash: str
    previous_word_count: int | None = None
    current_word_count: int = 0
    diff_summary: str | None = None
