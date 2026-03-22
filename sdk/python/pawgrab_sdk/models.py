"""Request/response models for the SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScrapeOptions:
    formats: list[str] = field(default_factory=lambda: ["markdown"])
    wait_for_js: bool | None = None
    timeout: int = 30000
    include_metadata: bool = True
    headers: dict[str, str] | None = None
    cookies: dict[str, str] | None = None
    screenshot: bool = False
    pdf: bool = False
    actions: list[dict] | None = None
    cache_ttl: int | None = None
    session_id: str | None = None
    llm_ready: bool = False
    css_selector: str | None = None
    excluded_tags: list[str] | None = None

    def to_dict(self) -> dict:
        d = {"formats": self.formats}
        if self.wait_for_js is not None:
            d["wait_for_js"] = self.wait_for_js
        if self.timeout != 30000:
            d["timeout"] = self.timeout
        if not self.include_metadata:
            d["include_metadata"] = False
        if self.headers:
            d["headers"] = self.headers
        if self.cookies:
            d["cookies"] = self.cookies
        if self.screenshot:
            d["screenshot"] = True
        if self.pdf:
            d["pdf"] = True
        if self.actions:
            d["actions"] = self.actions
        if self.cache_ttl is not None:
            d["cache_ttl"] = self.cache_ttl
        if self.session_id:
            d["session_id"] = self.session_id
        if self.llm_ready:
            d["llm_ready"] = True
        if self.css_selector:
            d["css_selector"] = self.css_selector
        if self.excluded_tags:
            d["excluded_tags"] = self.excluded_tags
        return d


@dataclass
class ExtractOptions:
    strategy: str = "llm"
    prompt: str | None = None
    schema_hint: dict | None = None
    json_schema: dict | None = None
    selectors: dict | None = None
    xpath_queries: dict | None = None
    patterns: dict | str | None = None
    table_index: int | None = None
    timeout: int = 30000

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"strategy": self.strategy}
        if self.prompt:
            d["prompt"] = self.prompt
        if self.schema_hint:
            d["schema_hint"] = self.schema_hint
        if self.json_schema:
            d["json_schema"] = self.json_schema
        if self.selectors:
            d["selectors"] = self.selectors
        if self.xpath_queries:
            d["xpath_queries"] = self.xpath_queries
        if self.patterns:
            d["patterns"] = self.patterns
        if self.table_index is not None:
            d["table_index"] = self.table_index
        if self.timeout != 30000:
            d["timeout"] = self.timeout
        return d


@dataclass
class CrawlOptions:
    max_pages: int = 10
    max_depth: int = 3
    formats: list[str] = field(default_factory=lambda: ["markdown"])
    strategy: str = "bfs"
    webhook_url: str | None = None
    allowed_domains: list[str] | None = None
    blocked_domains: list[str] | None = None
    keywords: list[str] | None = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "max_pages": self.max_pages,
            "max_depth": self.max_depth,
            "formats": self.formats,
            "strategy": self.strategy,
        }
        if self.webhook_url:
            d["webhook_url"] = self.webhook_url
        if self.allowed_domains:
            d["allowed_domains"] = self.allowed_domains
        if self.blocked_domains:
            d["blocked_domains"] = self.blocked_domains
        if self.keywords:
            d["keywords"] = self.keywords
        return d


@dataclass
class SearchOptions:
    num_results: int = 5
    formats: list[str] = field(default_factory=lambda: ["markdown"])
    include_metadata: bool = True

    def to_dict(self) -> dict:
        return {
            "num_results": self.num_results,
            "formats": self.formats,
            "include_metadata": self.include_metadata,
        }


@dataclass
class ScrapeResponse:
    success: bool
    url: str
    markdown: str | None = None
    html: str | None = None
    text: str | None = None
    metadata: dict | None = None
    cache_hit: bool = False
    warnings: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> ScrapeResponse:
        return cls(
            success=data.get("success", False),
            url=data.get("url", ""),
            markdown=data.get("markdown"),
            html=data.get("html"),
            text=data.get("text"),
            metadata=data.get("metadata"),
            cache_hit=data.get("cache_hit", False),
            warnings=data.get("warnings", []),
            raw=data,
        )


@dataclass
class ExtractResponse:
    success: bool
    url: str
    data: Any = None
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> ExtractResponse:
        return cls(
            success=data.get("success", False),
            url=data.get("url", ""),
            data=data.get("data"),
            raw=data,
        )


@dataclass
class CrawlJob:
    job_id: str
    status: str
    url: str
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> CrawlJob:
        return cls(
            job_id=data.get("job_id", ""),
            status=data.get("status", ""),
            url=data.get("url", ""),
            raw=data,
        )


@dataclass
class CrawlStatus:
    job_id: str
    status: str
    pages_scraped: int = 0
    results: list[dict] = field(default_factory=list)
    error: str | None = None
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> CrawlStatus:
        return cls(
            job_id=data.get("job_id", ""),
            status=data.get("status", ""),
            pages_scraped=data.get("pages_scraped", 0),
            results=data.get("results", []),
            error=data.get("error"),
            raw=data,
        )
