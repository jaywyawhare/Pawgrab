"""Models for the /v1/proxy endpoints."""

from pydantic import BaseModel, Field


class AddProxyRequest(BaseModel):
    url: str = Field(description="Proxy URL (e.g. http://user:pass@host:port)")


class AddProxyResponse(BaseModel):
    success: bool
    url: str
    message: str


class RemoveProxyResponse(BaseModel):
    success: bool
    url: str
    message: str


class ProxyEntry(BaseModel):
    url: str
    ok: bool = Field(description="Whether the proxy is currently healthy")
    speed: float = Field(description="Average response time in seconds")
    offered: int = Field(description="Total times this proxy was offered for use")
    succeed: int = Field(description="Total successful requests through this proxy")
    timeouts: int = Field(description="Total timeout failures")
    failures: int = Field(description="Total non-timeout failures")
    reanimated: int = Field(description="Times this proxy recovered from failure")
    recent_offered: int = Field(description="Requests offered in current sliding window")
    recent_succeed: int = Field(description="Successes in current sliding window")
    recent_timeouts: int = Field(description="Timeouts in current sliding window")
    recent_failures: int = Field(description="Failures in current sliding window")


class ProxyListResponse(BaseModel):
    proxies: list[ProxyEntry] = Field(description="All proxies in the pool")


class ProxyStatsResponse(BaseModel):
    total: int = Field(description="Total number of proxies in the pool")
    active: int = Field(description="Number of currently healthy proxies")
    evicted: int = Field(description="Number of currently unhealthy proxies")
    avg_speed: float = Field(description="Average response time of active proxies in seconds")
    policy: str = Field(description="Current proxy selection policy")
