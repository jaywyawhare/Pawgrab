"""Sitemap discovery and URL extraction."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import structlog
from curl_cffi.requests import AsyncSession

from pawgrab.config import settings

logger = structlog.get_logger()

_SITEMAP_PATHS = ["/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml"]


async def discover_urls(
    url: str,
    *,
    include_subdomains: bool = False,
    limit: int = 5000,
) -> tuple[list[str], str]:
    """Discover URLs via sitemap.xml, falling back to homepage link extraction.

    Returns (urls, source) where source is "sitemap" or "crawl".
    """
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    # Try sitemap paths
    for path in _SITEMAP_PATHS:
        sitemap_url = base + path
        urls = await _fetch_sitemap(sitemap_url, limit=limit)
        if urls:
            if not include_subdomains:
                domain = parsed.netloc.split(":")[0]
                urls = [u for u in urls if _matches_domain(u, domain)]
            return urls[:limit], "sitemap"

    # Fallback: extract links from homepage
    urls = await _extract_homepage_links(url, base, include_subdomains=include_subdomains)
    return urls[:limit], "crawl"


async def _fetch_sitemap(url: str, *, limit: int = 5000) -> list[str]:
    """Fetch and parse a sitemap XML, handling sitemap indexes recursively."""
    try:
        async with AsyncSession() as session:
            resp = await session.get(url, timeout=settings.sitemap_fetch_timeout, allow_redirects=True)
        if resp.status_code != 200:
            return []
        return _parse_sitemap_xml(resp.text, limit=limit)
    except Exception as exc:
        logger.info("sitemap_fetch_failed", url=url, error=str(exc))
        return []


def _parse_sitemap_xml(xml_text: str, *, limit: int = 5000) -> list[str]:
    """Parse sitemap XML, extracting <loc> tags."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    # Strip namespace for easier querying
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    urls: list[str] = []

    # Check if this is a sitemap index
    for sitemap in root.findall(f"{ns}sitemap"):
        loc = sitemap.find(f"{ns}loc")
        if loc is not None and loc.text:
            urls.append(loc.text.strip())

    # If it's a sitemap index, return the sub-sitemap URLs
    # (the caller can recursively fetch them)
    if urls:
        return urls[:limit]

    # Regular sitemap — extract URL locs
    for url_elem in root.findall(f"{ns}url"):
        loc = url_elem.find(f"{ns}loc")
        if loc is not None and loc.text:
            urls.append(loc.text.strip())
            if len(urls) >= limit:
                break

    return urls


def _matches_domain(url: str, domain: str) -> bool:
    """Check if URL belongs to the given domain (exact match)."""
    try:
        host = urlparse(url).netloc.split(":")[0]
        return host == domain
    except Exception:
        return False


async def _extract_homepage_links(
    url: str,
    base: str,
    *,
    include_subdomains: bool = False,
) -> list[str]:
    """Fallback: fetch homepage and extract all same-domain links."""
    try:
        async with AsyncSession() as session:
            resp = await session.get(url, timeout=settings.sitemap_fetch_timeout, allow_redirects=True)
        if resp.status_code != 200:
            return []
    except Exception:
        return []

    from bs4 import BeautifulSoup

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception:
        return []

    parsed_base = urlparse(base)
    domain = parsed_base.netloc.split(":")[0]
    seen: set[str] = set()
    urls: list[str] = []

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]

        # Resolve relative URLs
        if href.startswith("/"):
            href = base + href
        elif not href.startswith("http"):
            continue

        parsed = urlparse(href)
        if parsed.scheme not in ("http", "https"):
            continue

        host = parsed.netloc.split(":")[0]
        if include_subdomains:
            if not host.endswith(domain):
                continue
        else:
            if host != domain:
                continue

        # Normalize — strip query/fragment to deduplicate
        path = parsed.path.rstrip("/") or "/"
        normalized = f"{parsed.scheme}://{parsed.netloc}{path}"
        if normalized not in seen:
            seen.add(normalized)
            urls.append(normalized)

    return urls
