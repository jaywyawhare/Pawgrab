"""Heuristic detection of pages that require JS rendering, with per-domain caching."""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from urllib.parse import urlparse

_SPA_INDICATORS = [
    re.compile(r'<div\s+id=["\'](?:root|app|__next|__nuxt)["\']>\s*</div>', re.IGNORECASE),
    re.compile(r'<noscript>.*?enable javascript', re.IGNORECASE | re.DOTALL),
]

_FRAMEWORK_INDICATORS = [
    re.compile(r'__NEXT_DATA__', re.IGNORECASE),
    re.compile(r'window\.__NUXT__', re.IGNORECASE),
    re.compile(r'<div\s+id=["\']gatsby-', re.IGNORECASE),
]

_MINIMAL_CONTENT_THRESHOLD = 200  # chars of visible text

_CACHE_MAX_SIZE = 1000
_CACHE_TTL = 3600  # 1 hour


class _RenderingCache:
    """LRU cache with TTL for per-domain JS rendering decisions."""

    def __init__(self, max_size: int = _CACHE_MAX_SIZE, ttl: int = _CACHE_TTL):
        self._data: OrderedDict[str, tuple[bool, float]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl

    def get(self, domain: str) -> bool | None:
        entry = self._data.get(domain)
        if entry is None:
            return None
        value, ts = entry
        if time.monotonic() - ts > self._ttl:
            self._data.pop(domain, None)
            return None
        self._data.move_to_end(domain)
        return value

    def put(self, domain: str, needs_js: bool) -> None:
        if domain in self._data:
            self._data.move_to_end(domain)
        self._data[domain] = (needs_js, time.monotonic())
        while len(self._data) > self._max_size:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()


_cache = _RenderingCache()


def _extract_domain(url: str) -> str:
    """Extract domain from URL for cache key."""
    try:
        return urlparse(url).netloc
    except Exception:
        return ""


def _run_heuristics(html: str) -> bool:
    """Run JS rendering heuristics against HTML content."""
    for pattern in _SPA_INDICATORS:
        if pattern.search(html):
            return True

    for pattern in _FRAMEWORK_INDICATORS:
        if pattern.search(html):
            return True

    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < _MINIMAL_CONTENT_THRESHOLD:
        return True

    return False


def needs_js_rendering(html: str, url: str = "") -> bool:
    """Check if HTML looks like it needs JavaScript to render content.

    When a url is provided, results are cached per-domain to avoid
    redundant heuristic evaluation on subsequent requests.
    """
    domain = _extract_domain(url) if url else ""

    if domain:
        cached = _cache.get(domain)
        if cached is not None:
            return cached

    result = _run_heuristics(html)

    if domain:
        _cache.put(domain, result)

    return result
