"""Models for the /v1/scrape endpoint."""

from enum import Enum
from typing import Any, Literal

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
    SELECT = "select"
    CHECK = "check"
    UNCHECK = "uncheck"
    FOCUS = "focus"
    HOVER = "hover"
    FILL_FORM = "fill_form"
    SUBMIT_FORM = "submit_form"
    PRESS_KEY = "press_key"


class PageAction(BaseModel):
    type: ActionType
    selector: str | None = Field(default=None, description="CSS selector for the target element")
    text: str | None = Field(default=None, description="Text to type, JS code, key name, or select option value")
    direction: str | None = Field(default=None, description="Scroll direction: 'up' or 'down'")
    amount: int | None = Field(default=None, description="Pixels to scroll or milliseconds to wait")
    form_data: dict[str, str] | None = Field(default=None, description="Form fields to fill: {selector: value}")

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
        if t == ActionType.SELECT and (not self.selector or not self.text):
            raise ValueError("'select' action requires 'selector' and 'text' (option value)")
        if t in (ActionType.CHECK, ActionType.UNCHECK, ActionType.FOCUS, ActionType.HOVER) and not self.selector:
            raise ValueError(f"'{t.value}' action requires 'selector'")
        if t == ActionType.FILL_FORM and not self.form_data:
            raise ValueError("'fill_form' action requires 'form_data' ({selector: value})")
        if t == ActionType.SUBMIT_FORM and not self.selector:
            raise ValueError("'submit_form' action requires 'selector' (form selector)")
        if t == ActionType.PRESS_KEY and not self.text:
            raise ValueError("'press_key' action requires 'text' (key name, e.g. 'Enter', 'Tab')")
        return self


class ScrapeRequest(BaseModel):
    url: HttpUrl
    formats: list[OutputFormat] = Field(default=[OutputFormat.MARKDOWN], description="Output formats to return")
    wait_for_js: bool | None = Field(default=None, description="Force JS rendering. None = auto-detect based on page content")
    timeout: int = Field(default=30000, ge=1000, le=120000, description="Request timeout in milliseconds")
    include_metadata: bool = Field(default=True, description="Include page metadata (title, description, language, word count)")
    headers: dict[str, str] | None = Field(default=None, description="Custom HTTP request headers")
    cookies: dict[str, str] | None = Field(default=None, description="Custom cookies to send with the request")
    screenshot: bool = Field(default=False, description="Capture a screenshot (requires browser)")
    screenshot_fullpage: bool = Field(default=True, description="Capture full page screenshot vs viewport only")
    pdf: bool = Field(default=False, description="Capture page as PDF (requires browser)")
    monitor: bool = Field(default=False, description="Enable content change monitoring")
    monitor_ttl: int | None = Field(default=None, description="Content monitor TTL in seconds")
    citations: bool = Field(default=False, description="Convert inline links to numbered citation-style references")
    fit_markdown_query: str | None = Field(default=None, description="BM25 query to filter markdown sections by relevance")
    fit_markdown_top_k: int = Field(default=5, ge=1, le=50, description="Number of top sections to keep when using fit_markdown_query")
    actions: list[PageAction] | None = Field(default=None, description="Browser actions to execute before content extraction")
    excluded_tags: list[str] | None = Field(default=None, description="HTML tags to strip before extraction (e.g. ['nav', 'footer'])")
    excluded_selector: str | None = Field(default=None, max_length=2000, description="CSS selector for elements to remove before extraction")
    css_selector: str | None = Field(default=None, max_length=2000, description="CSS selector to scope content extraction to matching elements")
    word_count_threshold: int | None = Field(default=None, ge=1, le=10000, description="Minimum words per text block to keep")
    content_filter: Literal["pruning", "bm25"] | None = Field(default=None, description="Post-extraction content filter: 'pruning' or 'bm25'")
    content_filter_query: str | None = Field(default=None, description="Query string for BM25 content filter")
    browser_type: str | None = Field(default=None, description="Browser engine: 'chromium', 'firefox', or 'webkit'")
    geolocation: dict[str, float] | None = Field(default=None, description="Geolocation override: {latitude, longitude, accuracy}")
    text_mode: bool = Field(default=False, description="Disable images/CSS/fonts for faster loading")
    scroll_to_bottom: bool = Field(default=False, description="Auto-scroll to trigger lazy loading before extraction")
    capture_network: bool = Field(default=False, description="Capture network requests and responses")
    capture_console: bool = Field(default=False, description="Capture browser console messages")
    capture_mhtml: bool = Field(default=False, description="Save page as MHTML archive")
    extract_media: bool = Field(default=False, description="Extract images, videos, audio, and links")
    capture_ssl: bool = Field(default=False, description="Capture SSL certificate information")
    capture_websocket: bool = Field(default=False, description="Capture WebSocket messages during page load")
    llm_ready: bool = Field(default=False, description="Optimize output for LLM consumption: aggressive cleanup, token count estimation")
    cache_ttl: int | None = Field(default=None, ge=0, le=86400, description="Cache TTL in seconds. 0 = skip cache, None = use server default")
    session_id: str | None = Field(default=None, description="Session ID for persistent cookies/state across requests")


class PageMetadata(BaseModel):
    title: str | None = None
    description: str | None = None
    language: str | None = None
    url: str
    status_code: int
    word_count: int = 0
    token_count_estimate: int | None = Field(default=None, description="Estimated token count for LLM processing")
    retry_count: int = Field(default=0, description="Number of retry attempts needed to fetch the page")


class ScrapeResponse(BaseModel):
    success: bool
    url: str
    error: str | None = Field(default=None, description="Error message when success=False")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal warnings (e.g. fallback used, partial results)")
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
    screenshot_diff: dict | None = Field(default=None, description="Screenshot comparison with previous capture when monitor=True")
    network_requests: list[dict[str, Any]] | None = None
    console_logs: list[dict[str, Any]] | None = None
    mhtml_base64: str | None = None
    media: dict[str, Any] | None = None
    ssl_certificate: dict[str, Any] | None = None
    websocket_messages: list[dict[str, Any]] | None = Field(default=None, description="Captured WebSocket messages")
    cache_hit: bool = Field(default=False, description="Whether this response was served from cache")
