"""Models for the live interact endpoints (F3)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from pawgrab.models.common import OutputFormat
from pawgrab.models.scrape import PageAction


class InteractMode(StrEnum):
    CODE = "code"
    AI = "ai"


class StartLiveRequest(BaseModel):
    url: str = Field(description="URL to open and keep alive")
    formats: list[OutputFormat] = Field(default=[OutputFormat.MARKDOWN])
    timeout: int = Field(default=30_000, ge=1_000)


class StartLiveResponse(BaseModel):
    success: bool = True
    scrape_id: str
    url: str
    markdown: str | None = None
    html: str | None = None
    text: str | None = None
    title: str = ""
    current_url: str = ""
    live_view_url: str = ""


class InteractRequest(BaseModel):
    mode: InteractMode = InteractMode.CODE
    actions: list[PageAction] = Field(default_factory=list, description="Actions to run (mode=code)")
    prompt: str | None = Field(default=None, description="Natural-language instruction (mode=ai)")
    formats: list[OutputFormat] = Field(default=[OutputFormat.MARKDOWN])
    timeout: int = Field(default=30_000, ge=1_000)


class InteractResponse(BaseModel):
    success: bool = True
    scrape_id: str
    markdown: str | None = None
    html: str | None = None
    text: str | None = None
    title: str = ""
    current_url: str = ""
    action_warnings: list[str] = Field(default_factory=list)
    planned_actions: list[dict] = Field(default_factory=list)
    live_view_url: str = ""
