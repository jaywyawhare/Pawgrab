"""Models for the /agent endpoint (agentic, multi-step extraction)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class Effort(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AgentRequest(BaseModel):
    prompt: str = Field(description="Natural-language goal, e.g. 'find the pricing tiers and their monthly cost'")
    urls: list[HttpUrl] = Field(default_factory=list, description="Optional seed URLs; if empty the agent derives them via web search")
    json_schema: dict[str, Any] | None = Field(default=None, alias="schema", description="JSON schema the final data must satisfy")
    effort: Effort = Effort.MEDIUM
    max_steps: int | None = Field(default=None, ge=1, le=200, description="Overrides the effort-derived step budget")
    allowed_domains: list[str] = Field(default_factory=list, description="If set, the agent may only navigate to these domains")
    timeout: int = Field(default=30_000, ge=1_000, description="Per-fetch timeout in ms")

    model_config = {"populate_by_name": True}


class AgentStep(BaseModel):
    action: str = Field(description="fetch | search | finish")
    url: str | None = None
    query: str | None = None
    reason: str = ""
    tokens: int = 0


class AgentResponse(BaseModel):
    success: bool
    data: dict[str, Any] | None = None
    sources: list[str] = Field(default_factory=list)
    steps: list[AgentStep] = Field(default_factory=list)
    total_tokens: int = 0
    error: str | None = None
