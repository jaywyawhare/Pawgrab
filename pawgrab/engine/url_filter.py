"""Composable URL filter chain for crawl strategies.

DomainFilter      — allow/block domains
PathFilter        — regex path matching
ContentTypeFilter — filter by MIME type
DuplicateFilter   — seen-URL dedup
FilterChain       — compose multiple filters
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from urllib.parse import urlparse


class URLFilter(ABC):
    """Abstract base for URL filters."""

    @abstractmethod
    def accept(self, url: str) -> bool:
        """Return True if the URL should be accepted."""
        ...


class DomainFilter(URLFilter):
    """Allow or block URLs by domain."""

    def __init__(
        self,
        allowed_domains: list[str] | None = None,
        blocked_domains: list[str] | None = None,
    ):
        self.allowed_domains = set(allowed_domains) if allowed_domains else None
        self.blocked_domains = set(blocked_domains) if blocked_domains else set()

    def accept(self, url: str) -> bool:
        domain = urlparse(url).netloc.lower()
        if domain in self.blocked_domains:
            return False
        if self.allowed_domains is not None:
            return domain in self.allowed_domains
        return True


class PathFilter(URLFilter):
    """Filter URLs by regex matching on the path component."""

    def __init__(
        self,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ):
        self.include_re = [re.compile(p) for p in (include_patterns or [])]
        self.exclude_re = [re.compile(p) for p in (exclude_patterns or [])]

    def accept(self, url: str) -> bool:
        path = urlparse(url).path
        for pattern in self.exclude_re:
            if pattern.search(path):
                return False
        if self.include_re:
            return any(p.search(path) for p in self.include_re)
        return True


class ContentTypeFilter(URLFilter):
    """Filter URLs by file extension as a proxy for MIME type."""

    _DEFAULT_BLOCKED = frozenset({
        ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".bmp",
        ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm",
        ".zip", ".tar", ".gz", ".rar", ".7z",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".exe", ".dmg", ".apk", ".msi",
        ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
    })

    def __init__(
        self,
        allowed_extensions: set[str] | None = None,
        blocked_extensions: set[str] | None = None,
    ):
        self.allowed_extensions = allowed_extensions
        self.blocked_extensions = blocked_extensions or self._DEFAULT_BLOCKED

    def accept(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        dot_idx = path.rfind(".")
        if dot_idx == -1:
            return True  # no extension = likely HTML
        ext = path[dot_idx:]
        if ext in self.blocked_extensions:
            return False
        if self.allowed_extensions is not None:
            return ext in self.allowed_extensions
        return True


class DuplicateFilter(URLFilter):
    """Dedup URLs by normalized form."""

    def __init__(self):
        self._seen: set[str] = set()

    def accept(self, url: str) -> bool:
        normalized = self._normalize(url)
        if normalized in self._seen:
            return False
        self._seen.add(normalized)
        return True

    @staticmethod
    def _normalize(url: str) -> str:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/") or "/"
        return f"{parsed.scheme}://{parsed.netloc}{path}?{parsed.query}" if parsed.query else f"{parsed.scheme}://{parsed.netloc}{path}"

    def reset(self):
        self._seen.clear()

    @property
    def seen_count(self) -> int:
        return len(self._seen)


class FilterChain(URLFilter):
    """Compose multiple URL filters. All must accept for the URL to pass."""

    def __init__(self, filters: list[URLFilter] | None = None):
        self.filters: list[URLFilter] = filters or []

    def add(self, f: URLFilter) -> FilterChain:
        self.filters.append(f)
        return self

    def accept(self, url: str) -> bool:
        return all(f.accept(url) for f in self.filters)
