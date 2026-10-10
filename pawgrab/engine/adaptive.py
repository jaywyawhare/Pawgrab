"""Self-healing CSS extraction.

When a configured CSS selector stops matching — because a site changed its
markup — the extractor can relocate the intended element by comparing stored
*element signatures* against the new DOM. A signature is a compact, layout-
independent fingerprint of an element (tag, stable attributes, text, position
and ancestor path); the best-scoring candidate above a threshold is treated as
the same element and its field value is recovered.

Signatures persist between runs through a pluggable store (Redis or disk),
keyed by domain, so a selector that drifts on one request is healed on the
next.
"""

from __future__ import annotations

import difflib
from collections import OrderedDict
from typing import Any

import orjson
import structlog
from bs4 import BeautifulSoup, Tag

from pawgrab.config import settings

logger = structlog.get_logger()

# Attributes that tend to stay stable across redesigns, weighted highest.
_STABLE_ATTRS = ("id", "name", "role", "type", "aria-label", "itemprop", "href", "src", "alt", "placeholder")
_MAX_CANDIDATES = 4000
_MAX_TEXT = 160


def element_signature(el: Tag) -> dict[str, Any]:
    """Build a relocatable fingerprint of *el*."""
    classes = el.get("class") or []
    if isinstance(classes, str):
        classes = classes.split()
    data_attrs = {k: v for k, v in el.attrs.items() if k.startswith("data-") and isinstance(v, str)}
    stable = {k: el.get(k) for k in _STABLE_ATTRS if el.get(k)}
    text = " ".join((el.get_text(" ", strip=True) or "").split())[:_MAX_TEXT]
    parent = el.parent
    index = 0
    if isinstance(parent, Tag):
        index = [s for s in parent.find_all(el.name, recursive=False)].index(el) if el in parent.find_all(el.name, recursive=False) else 0
    path = []
    node = el.parent
    while isinstance(node, Tag) and len(path) < 6:
        path.append(node.name)
        node = node.parent
    return {
        "tag": el.name,
        "classes": sorted(classes),
        "stable": stable,
        "data": data_attrs,
        "text": text,
        "index": index,
        "path": path,
    }


def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def score_candidate(el: Tag, sig: dict[str, Any]) -> float:
    """Return a 0..1 similarity between *el* and a stored signature."""
    score = 0.0

    stable = sig.get("stable") or {}
    if stable:
        hits = sum(1 for k, v in stable.items() if el.get(k) == v)
        score += 0.30 * (hits / len(stable))
    else:
        score += 0.30 * 0.5  # no stable attrs to disprove identity — neutral

    classes = el.get("class") or []
    if isinstance(classes, str):
        classes = classes.split()
    score += 0.15 * _jaccard(classes, sig.get("classes") or [])

    score += 0.10 if el.name == sig.get("tag") else 0.0

    sig_text = sig.get("text") or ""
    if sig_text:
        cur_text = " ".join((el.get_text(" ", strip=True) or "").split())[:_MAX_TEXT]
        score += 0.30 * difflib.SequenceMatcher(None, cur_text, sig_text).ratio()
    else:
        score += 0.30 * 0.5

    sig_data = sig.get("data") or {}
    if sig_data:
        hits = sum(1 for k, v in sig_data.items() if el.get(k) == v)
        score += 0.15 * (hits / len(sig_data))
    else:
        score += 0.15 * 0.5

    return round(score, 4)


def find_by_signature(soup: BeautifulSoup, sig: dict[str, Any], *, min_score: float) -> Tag | None:
    """Locate the element in *soup* that best matches *sig* above *min_score*."""
    tag = sig.get("tag")
    candidates = soup.find_all(tag) if tag else soup.find_all(True)
    best: Tag | None = None
    best_score = 0.0
    for el in candidates[:_MAX_CANDIDATES]:
        s = score_candidate(el, sig)
        if s > best_score:
            best, best_score = el, s
    if best is not None and best_score >= min_score:
        return best
    return None


class AdaptiveStore:
    """Persist per-domain field signatures with an in-memory LRU in front."""

    _MAX_CACHE = 512

    def __init__(self) -> None:
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def _cache_get(self, domain: str) -> dict[str, Any] | None:
        if domain in self._cache:
            self._cache.move_to_end(domain)
            return self._cache[domain]
        return None

    def _cache_put(self, domain: str, sigs: dict[str, Any]) -> None:
        self._cache[domain] = sigs
        self._cache.move_to_end(domain)
        while len(self._cache) > self._MAX_CACHE:
            self._cache.popitem(last=False)

    async def load(self, domain: str) -> dict[str, Any]:
        cached = self._cache_get(domain)
        if cached is not None:
            return cached
        sigs = await self._load(domain)
        self._cache_put(domain, sigs)
        return sigs

    async def save(self, domain: str, signatures: dict[str, Any]) -> None:
        self._cache_put(domain, signatures)
        await self._save(domain, signatures)

    async def _load(self, domain: str) -> dict[str, Any]:
        raise NotImplementedError

    async def _save(self, domain: str, signatures: dict[str, Any]) -> None:
        raise NotImplementedError


class RedisSignatureStore(AdaptiveStore):
    """Store signatures in Redis, shared across API and workers."""

    def _key(self, domain: str) -> str:
        return f"pawgrab:adaptive:{domain}"

    async def _load(self, domain: str) -> dict[str, Any]:
        try:
            from pawgrab.queue.manager import get_redis

            redis = await get_redis()
            raw = await redis.get(self._key(domain))
            if raw:
                return orjson.loads(raw)
        except Exception as exc:
            logger.debug("adaptive_redis_load_failed", domain=domain, error=str(exc))
        return {}

    async def _save(self, domain: str, signatures: dict[str, Any]) -> None:
        try:
            from pawgrab.queue.manager import get_redis

            redis = await get_redis()
            await redis.set(self._key(domain), orjson.dumps(signatures).decode(), ex=settings.adaptive_ttl)
        except Exception as exc:
            logger.debug("adaptive_redis_save_failed", domain=domain, error=str(exc))


class DiskSignatureStore(AdaptiveStore):
    """Store signatures via the configured durable storage backend."""

    _PREFIX = "adaptive"

    @staticmethod
    def _safe_domain(domain: str) -> str:
        return domain.replace("/", "_").replace("\\", "_").replace(":", "_") or "_"

    async def _load(self, domain: str) -> dict[str, Any]:
        try:
            from pawgrab.engine.storage import get_storage

            data = await get_storage().retrieve(self._safe_domain(domain), prefix=self._PREFIX)
            return data or {}
        except Exception as exc:
            logger.debug("adaptive_disk_load_failed", domain=domain, error=str(exc))
            return {}

    async def _save(self, domain: str, signatures: dict[str, Any]) -> None:
        try:
            from pawgrab.engine.storage import get_storage

            await get_storage().store(self._safe_domain(domain), signatures, prefix=self._PREFIX)
        except Exception as exc:
            logger.debug("adaptive_disk_save_failed", domain=domain, error=str(exc))


_store: AdaptiveStore | None = None


def get_adaptive_store() -> AdaptiveStore:
    """Return the configured signature store (lazy singleton)."""
    global _store
    if _store is None:
        backend = settings.adaptive_store_backend
        if backend == "disk":
            _store = DiskSignatureStore()
        else:  # "redis" or "auto"
            _store = RedisSignatureStore()
    return _store
