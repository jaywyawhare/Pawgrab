"""Network request/response capture during browser-based fetching.

Provides structured logging of all network activity during page loads,
including URLs, status codes, headers, timing, and content types.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class CapturedRequest:
    url: str
    method: str
    resource_type: str
    headers: dict[str, str]
    timestamp: float = field(default_factory=time.time)
    response_status: int | None = None
    response_headers: dict[str, str] | None = None
    response_time_ms: float | None = None

    def to_dict(self) -> dict:
        d = {
            "url": self.url,
            "method": self.method,
            "resource_type": self.resource_type,
            "timestamp": self.timestamp,
        }
        if self.response_status is not None:
            d["response_status"] = self.response_status
            d["response_time_ms"] = self.response_time_ms
        if self.response_headers:
            d["response_content_type"] = self.response_headers.get("content-type", "")
        return d


class NetworkCapture:
    """Capture network requests and responses during page load."""

    def __init__(self):
        self._requests: dict[str, CapturedRequest] = {}
        self._completed: list[CapturedRequest] = []

    def on_request(self, request) -> None:
        """Handle a Playwright request event."""
        captured = CapturedRequest(
            url=request.url,
            method=request.method,
            resource_type=request.resource_type,
            headers=dict(request.headers),
        )
        self._requests[request.url] = captured

    def on_response(self, response) -> None:
        """Handle a Playwright response event."""
        captured = self._requests.get(response.url)
        if captured:
            captured.response_status = response.status
            captured.response_headers = dict(response.headers)
            captured.response_time_ms = (time.time() - captured.timestamp) * 1000
            self._completed.append(captured)

    def get_results(self) -> list[dict]:
        """Return all captured request/response pairs as dicts."""
        return [c.to_dict() for c in self._completed]

    @property
    def request_count(self) -> int:
        return len(self._completed)


class ConsoleCapture:
    """Capture browser console messages."""

    def __init__(self):
        self._messages: list[dict] = []

    def on_console(self, message) -> None:
        """Handle a Playwright console event."""
        self._messages.append({
            "type": message.type,
            "text": message.text,
        })

    def get_results(self) -> list[dict]:
        return self._messages.copy()
