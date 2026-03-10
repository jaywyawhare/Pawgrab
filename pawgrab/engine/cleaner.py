"""Content extraction using Readability algorithm.

Supports pre-processing: tag exclusion, CSS selector scoping,
word count thresholds, and content filters (pruning / BM25).
"""

from __future__ import annotations

import structlog
from bs4 import BeautifulSoup
from readabilipy import simple_json_from_html_string

logger = structlog.get_logger()


class CleanedContent:
    __slots__ = ("title", "content_html", "description", "language")

    def __init__(
        self,
        title: str,
        content_html: str,
        description: str = "",
        language: str = "",
    ):
        self.title = title
        self.content_html = content_html
        self.description = description
        self.language = language


def extract_content(
    html: str,
    url: str = "",
    *,
    excluded_tags: list[str] | None = None,
    excluded_selector: str | None = None,
    css_selector: str | None = None,
    word_count_threshold: int | None = None,
    content_filter: str | None = None,
    content_filter_query: str | None = None,
) -> CleanedContent:
    """Extract main content from HTML using readability.

    Pre-processing steps (applied before readability):
      - excluded_tags: strip matching HTML elements
      - excluded_selector: strip elements matching CSS selector
      - css_selector: scope extraction to matching elements only

    Post-processing steps (applied after readability):
      - word_count_threshold: filter out text blocks below threshold
      - content_filter: "pruning" or "bm25" filter on cleaned HTML
    """
    if not html or not html.strip():
        return CleanedContent(title="", content_html="")

    # Pre-process HTML before readability
    html = _preprocess(html, excluded_tags, excluded_selector, css_selector)

    try:
        article = simple_json_from_html_string(html, use_readability=True)
    except Exception:
        logger.warning("readability_failed", url=url, exc_info=True)
        article = {}

    title = article.get("title", "")
    content_html = article.get("content") or ""

    # Extract metadata from original HTML
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        logger.debug("lxml_fallback", url=url)
        soup = BeautifulSoup(html, "html.parser")

    description = ""
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc:
        description = meta_desc.get("content", "")

    language = ""
    html_tag = soup.find("html")
    if html_tag:
        language = html_tag.get("lang", "")

    # Post-process: word count threshold
    if word_count_threshold and word_count_threshold > 0:
        content_html = _apply_word_count_threshold(content_html, word_count_threshold)

    # Post-process: content filters
    if content_filter:
        content_html = _apply_content_filter(
            content_html, content_filter, content_filter_query
        )

    return CleanedContent(
        title=title or _extract_title(soup),
        content_html=content_html,
        description=description,
        language=language,
    )


def _preprocess(
    html: str,
    excluded_tags: list[str] | None,
    excluded_selector: str | None,
    css_selector: str | None,
) -> str:
    """Apply pre-processing filters to raw HTML before readability."""
    if not excluded_tags and not excluded_selector and not css_selector:
        return html

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    # Strip excluded tags
    if excluded_tags:
        for tag_name in excluded_tags:
            for el in soup.find_all(tag_name.lower()):
                el.decompose()

    # Strip elements matching CSS selector
    if excluded_selector:
        for el in soup.select(excluded_selector):
            el.decompose()

    # Scope to CSS selector — keep only matching elements
    if css_selector:
        matches = soup.select(css_selector)
        if matches:
            new_soup = BeautifulSoup("<html><body></body></html>", "html.parser")
            body = new_soup.find("body")
            for match in matches:
                body.append(match.__copy__())
            return str(new_soup)

    return str(soup)


def _apply_word_count_threshold(html: str, threshold: int) -> str:
    """Remove text blocks with fewer words than threshold."""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    for el in soup.find_all(["p", "li", "td", "th", "span", "div"]):
        text = el.get_text(strip=True)
        if text and len(text.split()) < threshold:
            # Only remove leaf-level elements to avoid removing containers
            if not el.find(["p", "li", "div", "section", "article"]):
                el.decompose()

    return str(soup)


def _apply_content_filter(html: str, filter_type: str, query: str | None) -> str:
    """Apply a content filter to cleaned HTML."""
    if filter_type == "pruning":
        from pawgrab.engine.filters import PruningContentFilter
        return PruningContentFilter().filter_html(html)
    elif filter_type == "bm25" and query:
        from pawgrab.engine.filters import BM25ContentFilter
        return BM25ContentFilter(query).filter_html(html)
    return html


def _extract_title(soup: BeautifulSoup) -> str:
    title_tag = soup.find("title")
    return title_tag.get_text(strip=True) if title_tag else ""
