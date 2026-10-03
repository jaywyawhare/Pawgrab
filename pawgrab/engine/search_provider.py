"""Vendored-in web search — a mini meta-search engine.

Reimplements, natively and dependency-free, the parts of SearXNG and SerpAPI
that matter, using Pawgrab's own curl_cffi TLS-impersonation stack:

  * SearXNG's architecture — one small parser per engine (build a request, parse
    the SERP into result dicts) plus its result merger: dedupe across engines by
    normalized URL, score as ``(∏ engine_weights × len(positions)) × Σ(1/position)``.
  * SearXNG's query controls — ``SearchParams`` carries page, time_range,
    safesearch, region and category, mapped to each engine's own parameters.
  * SearXNG's ResultContainer — ``search()`` returns organic results plus
    answers, infoboxes, suggestions, corrections, unresponsive_engines and timings.
  * SerpAPI's output — structured, ranked result objects and a metadata envelope,
    including a SERP-only (no-scrape) mode.

Engines (each declares the categories it serves):
  duckduckgo, bing (general/news/images/videos), brave, mojeek, yahoo,
  startpage — all scraped, keyless; google — Google's own Custom Search JSON API.
"""

from __future__ import annotations

import asyncio
import base64
import re
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlparse

import orjson
import structlog
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

from pawgrab.config import settings
from pawgrab.engine.antibot import random_impersonate, stealth_headers

logger = structlog.get_logger()
_SEARCH_TIMEOUT = 15
_RESULTS_PER_PAGE = 10

_ENGINE_WEIGHTS = {
    "duckduckgo": 1.0,
    "bing": 1.0,
    "brave": 1.0,
    "mojeek": 0.8,
    "yahoo": 0.8,
    "startpage": 0.9,
    "google": 1.3,
}

_META_ENGINES = {
    "general": ("duckduckgo", "bing", "mojeek"),
    "news": ("bing",),
    "images": ("bing",),
    "videos": ("bing",),
}

_ENGINE_CATEGORIES = {
    "duckduckgo": {"general"},
    "bing": {"general", "news", "images", "videos"},
    "brave": {"general"},
    "mojeek": {"general"},
    "yahoo": {"general"},
    "startpage": {"general"},
    "google": {"general", "images"},
}
_TIME_RANGES = ("day", "week", "month", "year")
_CATEGORIES = ("general", "news", "images", "videos")


@dataclass
class SearchParams:
    """Per-query controls (mirrors SearXNG's SearchQuery)."""

    page: int = 1
    time_range: str | None = None
    safesearch: int = 0
    region: str = "us-en"
    category: str = "general"

    def normalized(self) -> SearchParams:
        return SearchParams(
            page=max(1, int(self.page or 1)),
            time_range=self.time_range if self.time_range in _TIME_RANGES else None,
            safesearch=self.safesearch if self.safesearch in (0, 1, 2) else 0,
            region=self.region or "us-en",
            category=self.category if self.category in _CATEGORIES else "general",
        )


@dataclass
class EngineResult:
    results: list[dict] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)


@dataclass
class SearchResult:
    url: str
    title: str = ""
    content: str = ""
    type: str = "general"
    thumbnail: str = ""
    engines: set[str] = field(default_factory=set)
    positions: list[int] = field(default_factory=list)
    score: float = 0.0


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


def _r(url: str, title: str, content: str, type_: str = "general", thumbnail: str = "") -> dict:
    return {"url": url, "title": title, "content": content, "type": type_, "thumbnail": thumbnail}


def _ddg_real_url(href: str) -> str | None:
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
    """Scrape DuckDuckGo's no-JS HTML endpoint (general web)."""
    q: dict = {"q": query, "kl": params.region}
    if params.safesearch == 2:
        q["kp"] = "1"
    elif params.safesearch == 0:
        q["kp"] = "-1"
    if params.time_range:
        q["df"] = params.time_range[0]
    if params.page > 1:
        q["s"] = (params.page - 1) * _RESULTS_PER_PAGE * 3
    html = await _get_html("https://html.duckduckgo.com/html/", q)
    soup = _soup(html) if html else None
    if soup is None:
        return EngineResult()
    out: list[dict] = []
    for res in soup.select("div.result, div.web-result"):
        a = res.select_one("a.result__a")
        if not a:
            continue
        url = _ddg_real_url(a.get("href", ""))
        if not url:
            continue
        snippet = res.select_one(".result__snippet")
        out.append(_r(url, a.get_text(" ", strip=True), snippet.get_text(" ", strip=True) if snippet else ""))
        if len(out) >= num_results * 2:
            break
    return EngineResult(results=out)


def _bing_real_url(href: str) -> str | None:
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


_BING_TIME = {"day": 'ex1:"ez1"', "week": 'ex1:"ez2"', "month": 'ex1:"ez3"'}
_BING_ENDPOINT = {
    "general": "https://www.bing.com/search",
    "news": "https://www.bing.com/news/search",
    "images": "https://www.bing.com/images/search",
    "videos": "https://www.bing.com/videos/search",
}


async def _engine_bing(query: str, num_results: int, params: SearchParams) -> EngineResult:
    """Scrape Bing across web/news/images/videos."""
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
    html = await _get_html(_BING_ENDPOINT.get(params.category, _BING_ENDPOINT["general"]), q)
    soup = _soup(html) if html else None
    if soup is None:
        return EngineResult()
    if params.category == "images":
        return EngineResult(results=_parse_bing_images(soup, num_results))
    if params.category == "videos":
        return EngineResult(results=_parse_bing_videos(soup, num_results))
    if params.category == "news":
        return EngineResult(results=_parse_bing_news(soup))
    out: list[dict] = []
    for li in soup.select("li.b_algo"):
        a = li.select_one("h2 a") or li.select_one(".b_title a")
        if not a:
            continue
        url = _bing_real_url(a.get("href", ""))
        if not url:
            continue
        p = li.select_one("p")
        out.append(_r(url, a.get_text(" ", strip=True), p.get_text(" ", strip=True) if p else ""))
    suggestions = [a.get_text(" ", strip=True) for a in soup.select("#b_rs a, .b_rs a") if a.get_text(strip=True)]
    corrections = [a.get_text(" ", strip=True) for a in soup.select("#sp_requery a, .sp_recourse a") if a.get_text(strip=True)]
    return EngineResult(results=out, suggestions=suggestions, corrections=corrections)


def _parse_bing_news(soup) -> list[dict]:
    out: list[dict] = []
    for card in soup.select(".news-card, .newsitem, div.newsitem"):
        a = card.select_one("a.title") or card.select_one("a[href]")
        if not a:
            continue
        url = _bing_real_url(a.get("href", ""))
        if not url:
            continue
        snip = card.select_one(".snippet")
        out.append(_r(url, a.get_text(" ", strip=True), snip.get_text(" ", strip=True) if snip else "", "news"))
    return out


def _parse_bing_images(soup, num_results: int) -> list[dict]:
    out: list[dict] = []
    for a in soup.select("a.iusc"):
        meta = a.get("m")
        if not meta:
            continue
        try:
            data = orjson.loads(meta)
        except Exception:
            continue
        murl = data.get("murl")
        if not murl:
            continue
        out.append(_r(murl, data.get("t", ""), "", "images", thumbnail=data.get("turl", "")))
        if len(out) >= num_results * 2:
            break
    return out


def _parse_bing_videos(soup, num_results: int) -> list[dict]:
    out: list[dict] = []
    for a in soup.select("a.mc_vtvc_link, .dg_u a[href]"):
        url = _bing_real_url(a.get("href", ""))
        if not url:
            continue
        title = a.get("aria-label") or a.get_text(" ", strip=True)
        out.append(_r(url, title, "", "videos"))
        if len(out) >= num_results * 2:
            break
    return out


async def _engine_brave(query: str, num_results: int, params: SearchParams) -> EngineResult:
    q: dict = {"q": query, "source": "web"}
    if params.page > 1:
        q["offset"] = params.page - 1
    if params.safesearch:
        q["safesearch"] = "strict" if params.safesearch == 2 else "moderate"
    html = await _get_html("https://search.brave.com/search", q)
    soup = _soup(html) if html else None
    if soup is None:
        return EngineResult()
    out: list[dict] = []
    for snip in soup.select("#results .snippet, #results [data-type='web']"):
        a = snip.select_one("a[href^='http']")
        if not a:
            continue
        url = a.get("href", "")
        if not url or urlparse(url).netloc.endswith("brave.com"):
            continue
        title_el = snip.select_one(".title, .snippet-title") or a
        desc = snip.select_one(".snippet-description, .snippet-content")
        out.append(_r(url, title_el.get_text(" ", strip=True), desc.get_text(" ", strip=True) if desc else ""))
    return EngineResult(results=out)


async def _engine_mojeek(query: str, num_results: int, params: SearchParams) -> EngineResult:
    q: dict = {"q": query}
    if params.page > 1:
        q["s"] = (params.page - 1) * _RESULTS_PER_PAGE + 1
    if params.safesearch:
        q["safe"] = "1"
    html = await _get_html("https://www.mojeek.com/search", q)
    soup = _soup(html) if html else None
    if soup is None:
        return EngineResult()
    out: list[dict] = []
    for li in soup.select("ul.results-standard li, .results li"):
        a = li.select_one("h2 a, a.title")
        if not a:
            continue
        url = a.get("href", "")
        if not url.startswith("http"):
            continue
        p = li.select_one("p.s, .s")
        out.append(_r(url, a.get_text(" ", strip=True), p.get_text(" ", strip=True) if p else ""))
    return EngineResult(results=out)


_YAHOO_RU_RE = re.compile(r"RU=(.+?)/RK=")


def _yahoo_real_url(href: str) -> str | None:
    if not href:
        return None
    m = _YAHOO_RU_RE.search(href)
    if m:
        return unquote(m.group(1))
    return href if href.startswith("http") else None


async def _engine_yahoo(query: str, num_results: int, params: SearchParams) -> EngineResult:
    q: dict = {"p": query}
    if params.page > 1:
        q["b"] = (params.page - 1) * _RESULTS_PER_PAGE + 1
    html = await _get_html("https://search.yahoo.com/search", q)
    soup = _soup(html) if html else None
    if soup is None:
        return EngineResult()
    out: list[dict] = []
    for res in soup.select("div.algo, li div.algo-sr, #web li"):
        a = res.select_one("h3 a, a.d-ib")
        if not a:
            continue
        url = _yahoo_real_url(a.get("href", ""))
        if not url:
            continue
        snip = res.select_one(".compText, p")
        out.append(_r(url, a.get_text(" ", strip=True), snip.get_text(" ", strip=True) if snip else ""))
    return EngineResult(results=out)


async def _engine_startpage(query: str, num_results: int, params: SearchParams) -> EngineResult:
    q: dict = {"query": query}
    if params.page > 1:
        q["page"] = params.page
    html = await _get_html("https://www.startpage.com/sp/search", q)
    soup = _soup(html) if html else None
    if soup is None:
        return EngineResult()
    out: list[dict] = []
    for res in soup.select(".w-gl__result, .result"):
        a = res.select_one("a.w-gl__result-title, a.result-link, a[href^='http']")
        if not a:
            continue
        url = a.get("href", "")
        if not url.startswith("http"):
            continue
        desc = res.select_one(".w-gl__description, .description")
        out.append(_r(url, a.get_text(" ", strip=True), desc.get_text(" ", strip=True) if desc else ""))
    return EngineResult(results=out)


_GOOGLE_DATE = {"day": "d1", "week": "w1", "month": "m1", "year": "y1"}


async def _engine_google(query: str, num_results: int, params: SearchParams) -> EngineResult:
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
    if params.category == "images":
        api_params["searchType"] = "image"
    if params.time_range in _GOOGLE_DATE:
        api_params["dateRestrict"] = _GOOGLE_DATE[params.time_range]
    try:
        async with AsyncSession() as session:
            resp = await session.get("https://www.googleapis.com/customsearch/v1", params=api_params, timeout=_SEARCH_TIMEOUT)
        data = resp.json()
        cat = "images" if params.category == "images" else "general"
        results = [_r(i["link"], i.get("title", ""), i.get("snippet", ""), cat) for i in data.get("items", []) if i.get("link")]
        suggestions = [s.get("query", "") for s in (data.get("queries", {}) or {}).get("relatedSearch", [])]
        return EngineResult(results=results, suggestions=[s for s in suggestions if s])
    except Exception as exc:
        logger.warning("google_search_failed", error=str(exc))
        return EngineResult()


_ENGINE_NAMES = ("duckduckgo", "bing", "brave", "mojeek", "yahoo", "startpage", "google")


def _engine_callable(name: str):
    """Resolve an engine coroutine by name via the module namespace (patchable)."""
    return globals()[f"_engine_{name}"]


async def _fetch_instant_answers(query: str) -> tuple[list[str], list[dict]]:
    """Return (answers, infoboxes) from DuckDuckGo's Instant Answer API."""
    if not settings.search_instant_answers:
        return [], []
    try:
        async with AsyncSession(impersonate=random_impersonate(), timeout=_SEARCH_TIMEOUT) as session:
            resp = await session.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
                timeout=_SEARCH_TIMEOUT,
            )
        data = resp.json()
    except Exception as exc:
        logger.debug("instant_answer_failed", error=str(exc))
        return [], []
    if not isinstance(data, dict):
        return [], []
    answers: list[str] = []
    if data.get("Answer"):
        answers.append(str(data["Answer"]))
    if data.get("Definition"):
        answers.append(str(data["Definition"]))
    infoboxes: list[dict] = []
    if data.get("AbstractText"):
        infoboxes.append(
            {
                "title": data.get("Heading", ""),
                "content": data["AbstractText"],
                "url": data.get("AbstractURL", ""),
                "source": data.get("AbstractSource", ""),
            }
        )
    return answers, infoboxes


def _normalize_url(url: str) -> str:
    p = urlparse(url)
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = p.path.rstrip("/") or "/"
    return f"{host}{path}?{p.query}" if p.query else f"{host}{path}"


def _merge(engine_results: dict[str, list[dict]]) -> list[SearchResult]:
    by_key: dict[str, SearchResult] = {}
    for engine, results in engine_results.items():
        for position, item in enumerate(results, start=1):
            url = item["url"]
            key = _normalize_url(url)
            r = by_key.get(key)
            if r is None:
                r = SearchResult(
                    url=url,
                    title=item.get("title", ""),
                    content=item.get("content", ""),
                    type=item.get("type", "general"),
                    thumbnail=item.get("thumbnail", ""),
                )
                by_key[key] = r
            else:
                if url.startswith("https") and not r.url.startswith("https"):
                    r.url = url
                if len(item.get("title", "")) > len(r.title):
                    r.title = item["title"]
                if len(item.get("content", "")) > len(r.content):
                    r.content = item["content"]
                if not r.thumbnail and item.get("thumbnail"):
                    r.thumbnail = item["thumbnail"]
            r.engines.add(engine)
            r.positions.append(position)
    for r in by_key.values():
        weight = 1.0
        for e in r.engines:
            weight *= _ENGINE_WEIGHTS.get(e, 1.0)
        weight *= len(r.positions)
        r.score = sum(weight / p for p in r.positions)
    return sorted(by_key.values(), key=lambda r: r.score, reverse=True)


def _select_engines(provider: str, category: str) -> list[str]:
    if provider == "auto":
        candidates = _META_ENGINES.get(category, _META_ENGINES["general"])
    elif provider == "google" and not settings.google_search_api_key:
        candidates = _META_ENGINES.get(category, _META_ENGINES["general"])
    elif provider in _ENGINE_NAMES:
        candidates = (provider,)
    else:
        candidates = ("duckduckgo",)

    selected = [e for e in candidates if category in _ENGINE_CATEGORIES.get(e, set())]
    if not selected:
        selected = ["bing"] if category in _ENGINE_CATEGORIES["bing"] else ["duckduckgo"]
    return selected


async def _run_engine(name: str, query: str, num_results: int, params: SearchParams):
    """Run one engine under a per-engine timeout, returning (result, duration_ms)."""
    t0 = time.perf_counter()
    try:
        res = await asyncio.wait_for(
            _engine_callable(name)(query, num_results, params),
            timeout=settings.search_engine_timeout,
        )
    except TimeoutError:
        logger.warning("search_engine_timeout", engine=name)
        res = TimeoutError(name)
    except Exception as exc:  # noqa: BLE001 - engine isolation
        res = exc
    return res, round((time.perf_counter() - t0) * 1000, 1)


async def search(
    query: str,
    num_results: int = 5,
    *,
    page: int = 1,
    time_range: str | None = None,
    safesearch: int = 0,
    region: str = "us-en",
    category: str = "general",
) -> dict:
    """Run the configured engine(s) and return a SerpAPI-style envelope.

    ``{query, page, category, results, answers, infoboxes, suggestions,
    corrections, unresponsive_engines, timings, number_of_results}`` where each
    result is ``{position, title, link, snippet, type, thumbnail, engines, score}``.
    """
    params = SearchParams(page=page, time_range=time_range, safesearch=safesearch, region=region, category=category).normalized()
    engines = _select_engines(settings.search_provider, params.category)

    ia_task = asyncio.ensure_future(_fetch_instant_answers(query)) if params.category == "general" else None
    gathered = await asyncio.gather(*(_run_engine(name, query, num_results, params) for name in engines))
    engine_results: dict[str, list[dict]] = {}
    suggestions: set[str] = set()
    corrections: set[str] = set()
    unresponsive: list[str] = []
    timings: list[dict] = []
    for name, (res, dur) in zip(engines, gathered, strict=True):
        timings.append({"engine": name, "duration_ms": dur})
        if isinstance(res, EngineResult) and res.results:
            engine_results[name] = res.results
            suggestions.update(res.suggestions)
            corrections.update(res.corrections)
        else:
            if not isinstance(res, EngineResult):
                logger.warning("search_engine_failed", engine=name, error=str(res))
            unresponsive.append(name)
    answers: list[str] = []
    infoboxes: list[dict] = []
    if ia_task is not None:
        try:
            answers, infoboxes = await ia_task
        except Exception:
            answers, infoboxes = [], []
    merged = _merge(engine_results)[:num_results]
    results = [
        {
            "position": i + 1,
            "title": r.title,
            "link": r.url,
            "snippet": r.content,
            "type": r.type,
            "thumbnail": r.thumbnail,
            "engines": sorted(r.engines),
            "score": round(r.score, 4),
        }
        for i, r in enumerate(merged)
    ]
    return {
        "query": query,
        "page": params.page,
        "category": params.category,
        "results": results,
        "answers": answers,
        "infoboxes": infoboxes,
        "suggestions": sorted(suggestions),
        "corrections": sorted(corrections),
        "unresponsive_engines": unresponsive,
        "timings": timings,
        "number_of_results": len(results),
    }


async def search_structured(query: str, num_results: int = 5, **params) -> list[dict]:
    """Ranked, structured organic results (SerpAPI-style items)."""
    return (await search(query, num_results, **params))["results"]


async def search_web(query: str, num_results: int = 5, **params) -> list[str]:
    """Search the web and return a ranked list of result URLs."""
    return [r["link"] for r in await search_structured(query, num_results, **params)]
