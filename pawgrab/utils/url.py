"""URL normalization and utility functions."""

from functools import lru_cache
from urllib.parse import urljoin, urlparse


def normalize_url(url: str) -> str:
    """Normalize URL by removing fragments and trailing slashes."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    normalized = parsed._replace(fragment="", path=path)
    return normalized.geturl()


@lru_cache(maxsize=512)
def get_domain(url: str) -> str:
    """Extract domain from URL."""
    return urlparse(url).netloc


@lru_cache(maxsize=512)
def get_base_url(url: str) -> str:
    """Get scheme + host (e.g., https://example.com)."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def resolve_url(base: str, href: str) -> str:
    """Resolve a possibly relative URL against a base."""
    return urljoin(base, href)


def is_same_domain(url: str, base_url: str) -> bool:
    """Check if url belongs to the same domain as base_url."""
    return get_domain(url) == get_domain(base_url)
