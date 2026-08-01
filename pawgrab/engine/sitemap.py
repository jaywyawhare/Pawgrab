"""Sitemap discovery and URL extraction."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from urllib.parse import urlparse

import structlog
from curl_cffi.requests import AsyncSession

from pawgrab.config import settings

logger = structlog.get_logger()

_SITEMAP_PATHS = ["/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml"]
_MAX_SITEMAP_DEPTH = 3  # bound recursion into nested sitemap indexes
_DOCTYPE_RE = re.compile(r"<!DOCTYPE", re.IGNORECASE)


def _safe_parse(xml_text: str):
    """Parse sitemap XML, rejecting DTDs to prevent entity-expansion (billion-laughs) DoS.

    Untrusted sitemap XML comes from arbitrary target sites. defusedxml is used
    when available; otherwise we reject any document declaring a DOCTYPE (the
    vector for internal-entity expansion) before handing it to the stdlib parser.
    """
    if _DOCTYPE_RE.search(xml_text[:4096]):
        raise ValueError("sitemap declares a DOCTYPE; refusing to parse (XXE/billion-laughs)")
    try:
        import defusedxml.ElementTree as DefusedET

        return DefusedET.fromstring(xml_text)
    except ImportError:
        return ElementTree.fromstring(xml_text)


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

    for path in _SITEMAP_PATHS:
        sitemap_url = base + path
        urls = await _fetch_sitemap(sitemap_url, limit=limit)
        if urls:
            if not include_subdomains:
                domain = parsed.netloc.split(":")[0]
                urls = [u for u in urls if _matches_domain(u, domain)]
            return urls[:limit], "sitemap"

    urls = await _extract_homepage_links(url, base, include_subdomains=include_subdomains)
    return urls[:limit], "crawl"


async def _fetch_sitemap(
    url: str,
    *,
    limit: int = 5000,
    depth: int = 0,
    seen: set[str] | None = None,
) -> list[str]:
    """Fetch a sitemap and return *page* URLs, recursing into sitemap indexes.

    A ``<sitemapindex>`` lists child sitemaps, not pages; we fetch each child (up
    to ``_MAX_SITEMAP_DEPTH``) and aggregate their ``<url>`` locs so callers get
    real page URLs instead of sitemap-XML URLs.
    """
    seen = seen if seen is not None else set()
    if url in seen or depth > _MAX_SITEMAP_DEPTH:
        return []
    seen.add(url)

    try:
        async with AsyncSession() as session:
            resp = await session.get(url, timeout=settings.sitemap_fetch_timeout, allow_redirects=True)
        if resp.status_code != 200:
            return []
        kind, locs = _parse_sitemap(resp.text)
    except Exception as exc:
        logger.info("sitemap_fetch_failed", url=url, error=str(exc))
        return []

    if kind != "index":
        return locs[:limit]

    pages: list[str] = []
    for child in locs:
        if len(pages) >= limit:
            break
        pages.extend(await _fetch_sitemap(child, limit=limit - len(pages), depth=depth + 1, seen=seen))
    return pages[:limit]


def _parse_sitemap(xml_text: str) -> tuple[str, list[str]]:
    """Parse sitemap XML into ``(kind, locs)`` where kind is 'index' or 'urlset'."""
    try:
        root = _safe_parse(xml_text)
    except Exception:
        return "urlset", []

    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    index_locs: list[str] = []
    for sitemap in root.findall(f"{ns}sitemap"):
        loc = sitemap.find(f"{ns}loc")
        if loc is not None and loc.text:
            index_locs.append(loc.text.strip())
    if index_locs:
        return "index", index_locs

    page_locs: list[str] = []
    for url_elem in root.findall(f"{ns}url"):
        loc = url_elem.find(f"{ns}loc")
        if loc is not None and loc.text:
            page_locs.append(loc.text.strip())
    return "urlset", page_locs


def _parse_sitemap_xml(xml_text: str, *, limit: int = 5000) -> list[str]:
    """Parse sitemap XML, extracting <loc> tags (flat; index or urlset)."""
    _kind, locs = _parse_sitemap(xml_text)
    return locs[:limit]


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

        path = parsed.path.rstrip("/") or "/"
        normalized = f"{parsed.scheme}://{parsed.netloc}{path}"
        if normalized not in seen:
            seen.add(normalized)
            urls.append(normalized)

    return urls
