"""Vendored-in web search — a mini meta-search engine.

Reimplements, natively and dependency-free, the parts of SearXNG and SerpAPI
that matter, using Pawgrab's own curl_cffi TLS-impersonation stack:

  * SearXNG's architecture — one small parser per engine (build a request, parse
    the SERP into ``{url, title, content}``) plus its result merger: dedupe across
    engines by normalized URL, score as
    ``(∏ engine_weights × len(positions)) × Σ(1/position)``.
  * SearXNG's query controls — ``SearchParams`` carries page, time_range,
    safesearch and region, mapped to each engine's own parameters.
  * SearXNG's ResultContainer extras — ``search()`` returns not just organic
    results but ``suggestions`` and ``unresponsive_engines`` too.
  * SerpAPI's output — structured, ranked result objects
    (position/title/link/snippet/engines/score) plus a metadata envelope.

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
_RESULTS_PER_PAGE = 10

# SearXNG-style per-engine weights (google's API is highest-precision).
_ENGINE_WEIGHTS = {"duckduckgo": 1.0, "bing": 1.0, "brave": 1.0, "google": 1.3}
# Engines queried in "auto" meta-search mode (reliably scrapeable, keyless).
_META_ENGINES = ("duckduckgo", "bing")
_TIME_RANGES = ("day", "week", "month", "year")


@dataclass
class SearchParams:
    """Per-query controls (mirrors SearXNG's SearchQuery)."""

    page: int = 1
    time_range: str | None = None  # day | week | month | year
    safesearch: int = 0  # 0 off, 1 moderate, 2 strict
    region: str = "us-en"  # DDG-style region; mapped per engine

    def normalized(self) -> SearchParams:
        page = max(1, int(self.page or 1))
        tr = self.time_range if self.time_range in _TIME_RANGES else None
        ss = self.safesearch if self.safesearch in (0, 1, 2) else 0
        return SearchParams(page=page, time_range=tr, safesearch=ss, region=self.region or "us-en")


@dataclass
class EngineResult:
    results: list[tuple[str, str, str]] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


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


def _region_to_market(region: str) -> str:
    """DDG-style 'us-en' -> Bing/Google market 'en-US'."""
    parts = (region or "us-en").split("-")
    if len(parts) == 2:
        country, lang = parts
        return f"{lang.lower()}-{country.upper()}"
    return "en-US"


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


async def _engine_duckduckgo(query: str, num_results: int, params: SearchParams) -> EngineResult:
    """Scrape DuckDuckGo's no-JS HTML endpoint."""
    q: dict = {"q": query, "kl": params.region}
    # safesearch: DDG kp = 1 strict, -1 off; moderate = default (omitted).
    if params.safesearch == 2:
        q["kp"] = "1"
    elif params.safesearch == 0:
        q["kp"] = "-1"
    if params.time_range:
        q["df"] = params.time_range[0]  # d|w|m|y
    if params.page > 1:
        q["s"] = (params.page - 1) * _RESULTS_PER_PAGE * 3  # DDG offset step ~30
    html = await _get_html("https://html.duckduckgo.com/html/", q)
    soup = _soup(html) if html else None
    if soup is None:
        return EngineResult()
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
    suggestions = [s.get_text(" ", strip=True) for s in soup.select(".related-searches .related-searches__item, a.js-related-search") if s.get_text(strip=True)]
    return EngineResult(results=out, suggestions=suggestions)


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


# Bing time filter: filters=ex1:"ez<1|2|3>" ~ day/week/month.
_BING_TIME = {"day": 'ex1:"ez1"', "week": 'ex1:"ez2"', "month": 'ex1:"ez3"'}


async def _engine_bing(query: str, num_results: int, params: SearchParams) -> EngineResult:
    """Scrape Bing's results page (//ol[@id=b_results]/li.b_algo)."""
    count = max(1, min(num_results * 2, 50))
    q: dict = {
        "q": query,
        "count": count,
        "first": (params.page - 1) * count + 1,
        "mkt": _region_to_market(params.region),
        "adlt": {0: "off", 1: "moderate", 2: "strict"}[params.safesearch],
    }
    if params.time_range in _BING_TIME:
        q["filters"] = _BING_TIME[params.time_range]
    html = await _get_html("https://www.bing.com/search", q)
    soup = _soup(html) if html else None
    if soup is None:
        return EngineResult()
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
    suggestions = [a.get_text(" ", strip=True) for a in soup.select("#b_rs a, .b_rs a") if a.get_text(strip=True)]
    return EngineResult(results=out, suggestions=suggestions)


async def _engine_brave(query: str, num_results: int, params: SearchParams) -> EngineResult:
    """Scrape Brave Search results (best-effort; selectors tolerate markup drift)."""
    q: dict = {"q": query, "source": "web"}
    if params.page > 1:
        q["offset"] = params.page - 1
    if params.safesearch:
        q["safesearch"] = "strict" if params.safesearch == 2 else "moderate"
    html = await _get_html("https://search.brave.com/search", q)
    soup = _soup(html) if html else None
    if soup is None:
        return EngineResult()
    out: list[tuple[str, str, str]] = []
    for snip in soup.select("#results .snippet, #results [data-type='web']"):
        a = snip.select_one("a[href^='http']")
        if not a:
            continue
        url = a.get("href", "")
        if not url or urlparse(url).netloc.endswith("brave.com"):
            continue
        title_el = snip.select_one(".title, .snippet-title") or a
        desc = snip.select_one(".snippet-description, .snippet-content")
        out.append((url, title_el.get_text(" ", strip=True), desc.get_text(" ", strip=True) if desc else ""))
    return EngineResult(results=out)


# Google Custom Search dateRestrict codes.
_GOOGLE_DATE = {"day": "d1", "week": "w1", "month": "m1", "year": "y1"}


async def _engine_google(query: str, num_results: int, params: SearchParams) -> EngineResult:
    """Google's official Custom Search JSON API (the one keyed engine)."""
    if not settings.google_search_api_key:
        return EngineResult()
    api_params: dict = {
        "q": query,
        "key": settings.google_search_api_key,
        "cx": settings.google_search_cx,
        "num": max(1, min(num_results, 10)),
        "start": (params.page - 1) * num_results + 1,
        "safe": "active" if params.safesearch else "off",
    }
    if params.time_range in _GOOGLE_DATE:
        api_params["dateRestrict"] = _GOOGLE_DATE[params.time_range]
    try:
        async with AsyncSession() as session:
            resp = await session.get("https://www.googleapis.com/customsearch/v1", params=api_params, timeout=_SEARCH_TIMEOUT)
        data = resp.json()
        results = [(i["link"], i.get("title", ""), i.get("snippet", "")) for i in data.get("items", []) if i.get("link")]
        suggestions = [s.get("query", "") for s in (data.get("queries", {}) or {}).get("relatedSearch", [])]
        return EngineResult(results=results, suggestions=[s for s in suggestions if s])
    except Exception as exc:
        logger.warning("google_search_failed", error=str(exc))
        return EngineResult()


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
async def search(
    query: str,
    num_results: int = 5,
    *,
    page: int = 1,
    time_range: str | None = None,
    safesearch: int = 0,
    region: str = "us-en",
) -> dict:
    """Run the configured engine(s) and return a SerpAPI-style envelope.

    ``{query, page, results, suggestions, unresponsive_engines, number_of_results}``
    where each result is ``{position, title, link, snippet, engines, score}``.
    """
    params = SearchParams(page=page, time_range=time_range, safesearch=safesearch, region=region).normalized()
    engines = _select_engines(settings.search_provider)
    gathered = await asyncio.gather(
        *(_engine_callable(name)(query, num_results, params) for name in engines),
        return_exceptions=True,
    )

    engine_results: dict[str, list[tuple[str, str, str]]] = {}
    suggestions: set[str] = set()
    unresponsive: list[str] = []
    for name, res in zip(engines, gathered, strict=True):
        if isinstance(res, EngineResult):
            engine_results[name] = res.results
            suggestions.update(res.suggestions)
            if not res.results:
                unresponsive.append(name)
        else:
            logger.warning("search_engine_failed", engine=name, error=str(res))
            unresponsive.append(name)

    merged = _merge(engine_results)[:num_results]
    results = [
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
    return {
        "query": query,
        "page": params.page,
        "results": results,
        "suggestions": sorted(suggestions),
        "unresponsive_engines": unresponsive,
        "number_of_results": len(results),
    }


async def search_structured(query: str, num_results: int = 5, **params) -> list[dict]:
    """Ranked, structured organic results (SerpAPI-style items)."""
    return (await search(query, num_results, **params))["results"]


async def search_web(query: str, num_results: int = 5, **params) -> list[str]:
    """Search the web and return a ranked list of result URLs."""
    return [r["link"] for r in await search_structured(query, num_results, **params)]
