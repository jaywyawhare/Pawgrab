"""Models for the session API."""

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    ttl: int = Field(default=3600, ge=60, le=86400, description="Session TTL in seconds (default 1 hour)")
    cookies: dict[str, str] | None = Field(default=None, description="Initial cookies to set")
    headers: dict[str, str] | None = Field(default=None, description="Persistent headers for all requests in this session")


class CreateSessionResponse(BaseModel):
    success: bool = True
    session_id: str


class SessionInfo(BaseModel):
    session_id: str
    cookies: dict = Field(default_factory=dict)
    local_storage: dict = Field(default_factory=dict)
    headers: dict = Field(default_factory=dict)
    created_at: int = 0
    last_used: int = 0


class UpdateSessionRequest(BaseModel):
    cookies: dict[str, str] | None = Field(default=None, description="Cookies to merge into session")
    local_storage: dict | None = Field(default=None, description="Local storage data to set")
    headers: dict[str, str] | None = Field(default=None, description="Headers to update")
