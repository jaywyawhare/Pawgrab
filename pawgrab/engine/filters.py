"""Content filters for removing boilerplate and ranking by relevance.

PruningContentFilter — text density analysis to strip nav/footer/sidebar noise.
BM25ContentFilter   — TF-IDF cosine similarity scoring for query-relevant blocks.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from bs4 import BeautifulSoup, Tag

# Tags commonly containing boilerplate
_BOILERPLATE_TAGS = frozenset({
    "nav", "footer", "aside", "header",
    "form", "noscript", "figcaption",
})

# CSS class/id patterns associated with non-content regions
_BOILERPLATE_PATTERNS = re.compile(
    r"(sidebar|footer|header|nav|menu|breadcrumb|widget|banner|advert|cookie|"
    r"social|share|comment|related|popup|modal|overlay|newsletter|signup|"
    r"pagination|pager|copyright|disclaimer|masthead|topbar|toolbar)",
    re.IGNORECASE,
)


def _text_density(element: Tag) -> float:
    """Ratio of text length to total HTML length for an element."""
    text_len = len(element.get_text(strip=True))
    html_len = len(str(element))
    if html_len == 0:
        return 0.0
    return text_len / html_len


def _link_density(element: Tag) -> float:
    """Ratio of link text length to total text length."""
    text = element.get_text(strip=True)
    if not text:
        return 0.0
    link_text = "".join(
        a.get_text(strip=True) for a in element.find_all("a")
    )
    return len(link_text) / len(text)


class PruningContentFilter:
    """Remove boilerplate elements using text density analysis.

    Strategy:
      1. Remove known boilerplate tags (nav, footer, aside, etc.)
      2. Remove elements with boilerplate-associated class/id names
      3. Remove elements with very low text density (< threshold)
      4. Remove elements with very high link density (> threshold)
    """

    def __init__(
        self,
        text_density_threshold: float = 0.1,
        link_density_threshold: float = 0.6,
    ):
        self.text_density_threshold = text_density_threshold
        self.link_density_threshold = link_density_threshold

    def filter_html(self, html: str) -> str:
        """Return HTML with boilerplate elements removed."""
        if not html or not html.strip():
            return html

        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        # 1. Remove known boilerplate tags
        for tag_name in _BOILERPLATE_TAGS:
            for el in soup.find_all(tag_name):
                el.decompose()

        # 2. Remove elements with boilerplate class/id patterns
        for el in list(soup.find_all(True)):
            if el.decomposed if hasattr(el, "decomposed") else el.parent is None:
                continue
            classes = " ".join(el.get("class", []))
            el_id = el.get("id", "")
            if _BOILERPLATE_PATTERNS.search(classes) or _BOILERPLATE_PATTERNS.search(el_id):
                el.decompose()

        # 3+4. Remove low text-density / high link-density block elements
        for el in list(soup.find_all(["div", "section", "article", "table"])):
            if el.decomposed if hasattr(el, "decomposed") else el.parent is None:
                continue
            text = el.get_text(strip=True)
            if not text:
                el.decompose()
                continue
            if _text_density(el) < self.text_density_threshold:
                el.decompose()
                continue
            if _link_density(el) > self.link_density_threshold:
                el.decompose()

        return str(soup)


def _tokenize(text: str) -> list[str]:
    """Simple whitespace tokenizer with lowercasing."""
    return re.findall(r"[a-z0-9]+", text.lower())


class BM25ContentFilter:
    """Score and filter content blocks by TF-IDF cosine similarity to a query.

    Splits HTML into block-level elements, computes TF-IDF vectors, and
    returns only blocks whose cosine similarity to the query exceeds threshold.
    """

    def __init__(
        self,
        query: str,
        top_k: int = 10,
        similarity_threshold: float = 0.05,
    ):
        self.query = query
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold
        self._query_terms = _tokenize(query)

    def filter_html(self, html: str) -> str:
        """Return HTML containing only query-relevant content blocks."""
        if not self._query_terms or not html or not html.strip():
            return html

        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        # Extract block-level elements
        blocks: list[Tag] = []
        for el in soup.find_all(
            ["p", "div", "section", "article", "li", "td", "th",
             "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre"]
        ):
            text = el.get_text(strip=True)
            if text and len(text) > 20:
                blocks.append(el)

        if not blocks:
            return html

        # Tokenize all blocks
        block_tokens = [_tokenize(b.get_text()) for b in blocks]

        # Build document frequency
        n = len(blocks)
        df: Counter[str] = Counter()
        for tokens in block_tokens:
            for term in set(tokens):
                df[term] += 1

        # Compute IDF for query terms
        idf: dict[str, float] = {}
        for term in self._query_terms:
            if df[term] > 0:
                idf[term] = math.log((n + 1) / (df[term] + 1)) + 1
            else:
                idf[term] = math.log(n + 1) + 1

        # Score each block by cosine similarity with query
        scored: list[tuple[int, float, Tag]] = []
        query_vec = {t: idf.get(t, 0) for t in self._query_terms}
        query_norm = math.sqrt(sum(v * v for v in query_vec.values())) or 1.0

        for i, (block, tokens) in enumerate(zip(blocks, block_tokens)):
            tf_map = Counter(tokens)
            doc_vec: dict[str, float] = {}
            for term in self._query_terms:
                tf = tf_map.get(term, 0)
                doc_vec[term] = tf * idf.get(term, 0)

            dot = sum(query_vec.get(t, 0) * doc_vec.get(t, 0) for t in self._query_terms)
            doc_norm = math.sqrt(sum(v * v for v in doc_vec.values())) or 1.0
            similarity = dot / (query_norm * doc_norm)

            if similarity >= self.similarity_threshold:
                scored.append((i, similarity, block))

        # Sort by score descending, take top_k
        scored.sort(key=lambda x: x[1], reverse=True)
        kept = scored[:self.top_k]

        if not kept:
            return html

        # Re-sort by document order
        kept.sort(key=lambda x: x[0])

        # Build new HTML from kept blocks
        new_soup = BeautifulSoup("<div></div>", "html.parser")
        container = new_soup.find("div")
        for _, _, block in kept:
            container.append(block.__copy__())

        return str(container)
