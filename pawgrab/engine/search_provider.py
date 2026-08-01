"""Vendored-in web search — a mini meta-search engine.

Rather than depend on a paid API (SerpAPI) or an external service (SearXNG), the
search capability of both is reimplemented here, using Pawgrab's own curl_cffi
TLS-impersonation stack. Two ideas are borrowed directly from their internals:

  * SearXNG's architecture — one small module per engine that (a) builds a
    request and (b) parses the result page into ``{url, title, content}`` — plus
    its result merger: results are deduped across engines by normalized URL and
    scored as ``(∏ engine_weights × len(positions)) × Σ(1/position)`` so a page
    surfaced by several engines, high up, ranks first.
  * SerpAPI's output — ``search_structured`` returns ranked, structured result
    objects (position/title/link/snippet/engines/score), not just URLs.

Providers: ``duckduckgo`` (default, scraped), ``bing`` (scraped),
``brave`` (scraped), ``auto`` (meta-search across DDG+Bing, merged), and
``google`` (the one keyed option, Google's own Custom Search JSON API).
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlparse

import structlog
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

from pawgrab.config import settings
from pawgrab.engine.antibot import random_impersonate, stealth_headers

logger = structlog.get_logger()

_SEARCH_TIMEOUT = 15

# SearXNG-style per-engine weights (google's API is highest-precision).
_ENGINE_WEIGHTS = {"duckduckgo": 1.0, "bing": 1.0, "brave": 1.0, "google": 1.3}
# Engines queried in "auto" meta-search mode (reliably scrapeable, keyless).
_META_ENGINES = ("duckduckgo", "bing")


@dataclass
class SearchResult:
    url: str
    title: str = ""
    content: str = ""
    engines: set[str] = field(default_factory=set)
    positions: list[int] = field(default_factory=list)
    score: float = 0.0


# --------------------------------------------------------------------------- #
# HTTP + parsing helpers
# --------------------------------------------------------------------------- #
async def _get_html(url: str, params: dict) -> str | None:
    """Fetch a SERP page with browser TLS impersonation. Returns HTML or None."""
    try:
        async with AsyncSession(impersonate=random_impersonate(), timeout=_SEARCH_TIMEOUT) as session:
            resp = await session.get(url, params=params, headers=stealth_headers(), timeout=_SEARCH_TIMEOUT, allow_redirects=True)
        if resp.status_code != 200:
            logger.warning("search_bad_status", url=url, status=resp.status_code)
            return None
        return resp.text
    except Exception as exc:
        logger.warning("search_fetch_failed", url=url, error=str(exc))
        return None


def _soup(html: str) -> BeautifulSoup | None:
    try:
        return BeautifulSoup(html, "html.parser")
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Per-engine parsers  (SearXNG's request/response split)
# --------------------------------------------------------------------------- #
def _ddg_real_url(href: str) -> str | None:
    """Resolve a DuckDuckGo result href (often a /l/?uddg= redirect) to its target."""
    if not href:
        return None
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        uddg = parse_qs(parsed.query).get("uddg")
        return unquote(uddg[0]) if uddg else None
    return href if parsed.scheme in ("http", "https") else None


async def _engine_duckduckgo(query: str, num_results: int) -> list[tuple[str, str, str]]:
    """Scrape DuckDuckGo's no-JS HTML endpoint into (url, title, content) tuples."""
    html = await _get_html("https://html.duckduckgo.com/html/", {"q": query, "kl": "us-en"})
    soup = _soup(html) if html else None
    if soup is None:
        return []
    out: list[tuple[str, str, str]] = []
    for res in soup.select("div.result, div.web-result"):
        a = res.select_one("a.result__a")
        if not a:
            continue
        url = _ddg_real_url(a.get("href", ""))
        if not url:
            continue
        snippet = res.select_one(".result__snippet")
        out.append((url, a.get_text(" ", strip=True), snippet.get_text(" ", strip=True) if snippet else ""))
        if len(out) >= num_results * 2:
            break
    return out


def _bing_real_url(href: str) -> str | None:
    """Decode Bing's /ck/a?u=a1<base64url> tracking redirect (SearXNG's rule)."""
    if not href:
        return None
    parsed = urlparse(href)
    if parsed.scheme not in ("http", "https"):
        return None
    if parsed.netloc.endswith("bing.com") and parsed.path.startswith("/ck/"):
        u = parse_qs(parsed.query).get("u")
        if not u:
            return None
        token = u[0][2:] if u[0].startswith("a1") else u[0]
        try:
            padded = token + "=" * (-len(token) % 4)
            return base64.urlsafe_b64decode(padded).decode("utf-8", "replace")
        except Exception:
            return None
    return href


async def _engine_bing(query: str, num_results: int) -> list[tuple[str, str, str]]:
    """Scrape Bing's results page (//ol[@id=b_results]/li.b_algo)."""
    html = await _get_html("https://www.bing.com/search", {"q": query, "count": max(1, min(num_results * 2, 50))})
    soup = _soup(html) if html else None
    if soup is None:
        return []
    out: list[tuple[str, str, str]] = []
    for li in soup.select("li.b_algo"):
        a = li.select_one("h2 a") or li.select_one(".b_title a")
        if not a:
            continue
        url = _bing_real_url(a.get("href", ""))
        if not url:
            continue
        p = li.select_one("p")
        out.append((url, a.get_text(" ", strip=True), p.get_text(" ", strip=True) if p else ""))
    return out


async def _engine_brave(query: str, num_results: int) -> list[tuple[str, str, str]]:
    """Scrape Brave Search results (best-effort; selectors tolerate markup drift)."""
    html = await _get_html("https://search.brave.com/search", {"q": query, "source": "web"})
    soup = _soup(html) if html else None
    if soup is None:
        return []
    out: list[tuple[str, str, str]] = []
    for snip in soup.select("#results .snippet, #results [data-type='web']"):
        a = snip.select_one("a[href^='http']")
        if not a:
            continue
        url = a.get("href", "")
        host = urlparse(url).netloc
        if not url or host.endswith("brave.com"):
            continue
        title_el = snip.select_one(".title, .snippet-title") or a
        desc = snip.select_one(".snippet-description, .snippet-content")
        out.append((url, title_el.get_text(" ", strip=True), desc.get_text(" ", strip=True) if desc else ""))
    return out


async def _engine_google(query: str, num_results: int) -> list[tuple[str, str, str]]:
    """Google's official Custom Search JSON API (the one keyed engine)."""
    if not settings.google_search_api_key:
        return []
    try:
        async with AsyncSession() as session:
            resp = await session.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "q": query,
                    "key": settings.google_search_api_key,
                    "cx": settings.google_search_cx,
                    "num": max(1, min(num_results, 10)),
                },
                timeout=_SEARCH_TIMEOUT,
            )
        data = resp.json()
        return [(i["link"], i.get("title", ""), i.get("snippet", "")) for i in data.get("items", []) if i.get("link")]
    except Exception as exc:
        logger.warning("google_search_failed", error=str(exc))
        return []


_ENGINE_NAMES = ("duckduckgo", "bing", "brave", "google")


def _engine_callable(name: str):
    """Resolve an engine coroutine by name via the module namespace.

    Looked up dynamically (not a captured dict) so it always reflects the current
    binding — which also keeps the engines individually patchable in tests.
    """
    return globals()[f"_engine_{name}"]


# --------------------------------------------------------------------------- #
# Result merger  (SearXNG's calculate_score / duplicate merge)
# --------------------------------------------------------------------------- #
def _normalize_url(url: str) -> str:
    """Dedup key: lowercased host without www, path without trailing slash, no fragment."""
    p = urlparse(url)
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = p.path.rstrip("/") or "/"
    return f"{host}{path}?{p.query}" if p.query else f"{host}{path}"


def _merge(engine_results: dict[str, list[tuple[str, str, str]]]) -> list[SearchResult]:
    """Merge per-engine results and score them the way SearXNG does."""
    by_key: dict[str, SearchResult] = {}
    for engine, results in engine_results.items():
        for position, (url, title, content) in enumerate(results, start=1):
            key = _normalize_url(url)
            r = by_key.get(key)
            if r is None:
                r = SearchResult(url=url, title=title, content=content)
                by_key[key] = r
            else:
                # Prefer https, and the longer title/content (SearXNG merge rules).
                if url.startswith("https") and not r.url.startswith("https"):
                    r.url = url
                if len(title) > len(r.title):
                    r.title = title
                if len(content) > len(r.content):
                    r.content = content
            r.engines.add(engine)
            r.positions.append(position)

    for r in by_key.values():
        weight = 1.0
        for e in r.engines:
            weight *= _ENGINE_WEIGHTS.get(e, 1.0)
        weight *= len(r.positions)
        r.score = sum(weight / p for p in r.positions)

    return sorted(by_key.values(), key=lambda r: r.score, reverse=True)


def _select_engines(provider: str) -> list[str]:
    if provider == "auto":
        return list(_META_ENGINES)
    if provider == "google" and not settings.google_search_api_key:
        return list(_META_ENGINES)  # fall back to scraped meta-search
    if provider in _ENGINE_NAMES:
        return [provider]
    return ["duckduckgo"]


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
async def search_structured(query: str, num_results: int = 5) -> list[dict]:
    """Run the configured engine(s), merge, and return ranked structured results.

    SerpAPI-style: each item is ``{position, title, link, snippet, engines, score}``.
    """
    engines = _select_engines(settings.search_provider)
    gathered = await asyncio.gather(
        *(_engine_callable(name)(query, num_results) for name in engines),
        return_exceptions=True,
    )
    engine_results: dict[str, list[tuple[str, str, str]]] = {}
    for name, res in zip(engines, gathered, strict=True):
        if isinstance(res, list):
            engine_results[name] = res
        else:
            logger.warning("search_engine_failed", engine=name, error=str(res))

    merged = _merge(engine_results)[:num_results]
    return [
        {
            "position": i + 1,
            "title": r.title,
            "link": r.url,
            "snippet": r.content,
            "engines": sorted(r.engines),
            "score": round(r.score, 4),
        }
        for i, r in enumerate(merged)
    ]


async def search_web(query: str, num_results: int = 5) -> list[str]:
    """Search the web and return a ranked list of result URLs."""
    return [r["link"] for r in await search_structured(query, num_results)]
