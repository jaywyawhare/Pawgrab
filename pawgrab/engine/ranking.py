"""Relevance ranking of URLs / documents against a query.

Lexical by default (BM25-lite over bag-of-words, zero network, zero deps beyond
the stdlib + our tokenizer). An optional embeddings path can be layered on by
callers that have an embeddings provider. Shared by /map (F2) and the index (F4).
"""

from __future__ import annotations

import math
from collections import Counter
from urllib.parse import unquote, urlsplit

from pawgrab.utils.text import tokenize

# BM25 free parameters — standard defaults.
_K1 = 1.5
_B = 0.75


def url_to_text(url: str) -> str:
    """Derive a bag-of-words document from a URL's host, path, and query slugs."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    host = parts.hostname or ""
    # Drop the TLD-ish noise but keep meaningful subdomain/brand tokens.
    path = unquote(parts.path or "").replace("-", " ").replace("_", " ").replace("/", " ")
    query = unquote(parts.query or "").replace("=", " ").replace("&", " ")
    return f"{host} {path} {query}"


def _bm25_scores(query: str, docs: list[str]) -> list[float]:
    """Score each doc against the query with Okapi BM25 over the candidate set."""
    q_terms = set(tokenize(query))
    if not q_terms or not docs:
        return [0.0] * len(docs)

    tokenized = [tokenize(d) for d in docs]
    doc_lens = [len(t) for t in tokenized]
    avgdl = (sum(doc_lens) / len(doc_lens)) or 1.0
    n = len(docs)

    # Document frequency per query term.
    df: Counter[str] = Counter()
    for toks in tokenized:
        present = set(toks)
        for term in q_terms:
            if term in present:
                df[term] += 1

    scores: list[float] = []
    for toks, dl in zip(tokenized, doc_lens, strict=True):
        tf = Counter(toks)
        score = 0.0
        for term in q_terms:
            if term not in tf:
                continue
            # BM25 idf with the +0.5 smoothing; floored at 0 so common terms don't go negative.
            idf = max(0.0, math.log((n - df[term] + 0.5) / (df[term] + 0.5) + 1.0))
            freq = tf[term]
            denom = freq + _K1 * (1 - _B + _B * dl / avgdl)
            score += idf * (freq * (_K1 + 1)) / (denom or 1.0)
        scores.append(score)
    return scores


def rank_urls(
    query: str,
    urls: list[str],
    titles: list[str] | None = None,
) -> list[tuple[str, float]]:
    """Rank URLs by lexical relevance to the query.

    Each URL's document is its host/path/slug text plus any sitemap title. Returns
    ``(url, score)`` sorted by score descending; ties keep the original order.
    """
    if not urls:
        return []
    titles = titles or [""] * len(urls)
    docs = [f"{url_to_text(u)} {t or ''}" for u, t in zip(urls, titles, strict=False)]
    scores = _bm25_scores(query, docs)
    ranked = sorted(zip(urls, scores, strict=True), key=lambda p: p[1], reverse=True)
    return ranked


def rank_documents(
    query: str,
    items: list[dict],
    text_key: str = "text",
    id_key: str = "url",
) -> list[tuple[dict, float]]:
    """Rank arbitrary documents (dicts) by lexical relevance of ``text_key``."""
    if not items:
        return []
    docs = [str(it.get(text_key, "")) for it in items]
    scores = _bm25_scores(query, docs)
    return sorted(zip(items, scores, strict=True), key=lambda p: p[1], reverse=True)


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length dense vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
