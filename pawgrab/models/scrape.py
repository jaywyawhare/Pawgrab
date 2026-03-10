"""Models for the /v1/scrape endpoint."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, model_validator

from .common import OutputFormat


class ActionType(str, Enum):
    CLICK = "click"
    TYPE = "type"
    SCROLL = "scroll"
    WAIT = "wait"
    WAIT_FOR = "wait_for"
    SCREENSHOT = "screenshot"
    EXECUTE_JS = "execute_js"


class PageAction(BaseModel):
    type: ActionType
    selector: str | None = None
    text: str | None = None
    direction: str | None = None  # "up" or "down" for scroll
    amount: int | None = None  # px for scroll, ms for wait

    @model_validator(mode="after")
    def validate_fields(self):
        t = self.type
        if t in (ActionType.CLICK, ActionType.WAIT_FOR) and not self.selector:
            raise ValueError(f"'{t.value}' action requires 'selector'")
        if t == ActionType.TYPE and (not self.selector or not self.text):
            raise ValueError("'type' action requires 'selector' and 'text'")
        if t == ActionType.SCROLL:
            if self.direction not in ("up", "down"):
                raise ValueError("'scroll' action requires 'direction' ('up' or 'down')")
            if self.amount is None:
                self.amount = 500
        if t == ActionType.WAIT:
            if self.amount is None:
                raise ValueError("'wait' action requires 'amount' (ms)")
        if t == ActionType.EXECUTE_JS and not self.text:
            raise ValueError("'execute_js' action requires 'text' (JS code)")
        return self


class ScrapeRequest(BaseModel):
    url: HttpUrl
    formats: list[OutputFormat] = [OutputFormat.MARKDOWN]
    wait_for_js: bool | None = None  # None = auto-detect
    timeout: int = Field(default=30000, ge=1000, le=120000)
    include_metadata: bool = True
    headers: dict[str, str] | None = None  # custom request headers
    cookies: dict[str, str] | None = None  # custom cookies
    screenshot: bool = False
    screenshot_fullpage: bool = True
    pdf: bool = False
    monitor: bool = False
    monitor_ttl: int | None = None
    # Citation-style references: converts inline links to numbered footnotes
    citations: bool = False
    # Fit markdown: BM25 relevance filtering — only keeps sections relevant to this query
    fit_markdown_query: str | None = None
    fit_markdown_top_k: int = Field(default=5, ge=1, le=50)
    # Page actions — executed sequentially before content extraction
    actions: list[PageAction] | None = None
    # Content processing — tag exclusion, CSS scoping, word count filtering
    excluded_tags: list[str] | None = None  # HTML tags to strip (e.g. ["nav", "footer"])
    excluded_selector: str | None = None  # CSS selector for elements to remove
    css_selector: str | None = None  # CSS selector to scope content extraction
    word_count_threshold: int | None = None  # min words per text block to keep
    # Content filters
    content_filter: str | None = None  # "pruning" or "bm25"
    content_filter_query: str | None = None  # query for BM25 content filter
    # Browser enhancements
    browser_type: str | None = None  # "chromium", "firefox", "webkit"
    geolocation: dict[str, float] | None = None  # {"latitude": ..., "longitude": ..., "accuracy": ...}
    text_mode: bool = False  # disable images/CSS/fonts for speed
    scroll_to_bottom: bool = False  # auto-scroll to trigger lazy loading
    # Capture options
    capture_network: bool = False  # intercept network requests/responses
    capture_console: bool = False  # capture browser console messages
    capture_mhtml: bool = False  # save MHTML snapshot
    extract_media: bool = False  # extract images/videos/audio/links
    capture_ssl: bool = False  # capture SSL certificate info


class PageMetadata(BaseModel):
    title: str | None = None
    description: str | None = None
    language: str | None = None
    url: str
    status_code: int
    word_count: int = 0


class ScrapeResponse(BaseModel):
    success: bool
    url: str
    warning: str | None = None
    metadata: PageMetadata | None = None
    markdown: str | None = None
    html: str | None = None
    text: str | None = None
    json_data: list[dict[str, Any]] | None = None
    csv_data: str | None = None
    xml_data: str | None = None
    screenshot_base64: str | None = None
    pdf_base64: str | None = None
    diff: Any | None = None  # ContentDiff when monitor=True
    # Capture results (Phase 6)
    network_requests: list[dict[str, Any]] | None = None
    console_logs: list[dict[str, Any]] | None = None
    mhtml_base64: str | None = None
    media: dict[str, Any] | None = None  # images, videos, audio, links
    ssl_certificate: dict[str, Any] | None = None
