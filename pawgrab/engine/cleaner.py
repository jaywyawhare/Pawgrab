"""Content extraction via Readability."""

from __future__ import annotations

import re

import structlog
from bs4 import BeautifulSoup
from lxml import html as lxml_html
from readability import Document as ReadabilityDocument

from pawgrab.utils.text import make_soup

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

_TAG_RE = re.compile(r"<[^>]+>")

_BOILERPLATE_XPATHS = (
    "//script", "//style", "//noscript", "//svg", "//iframe",
    "//nav", "//header", "//footer", "//aside",
    '//*[@role="navigation"]', '//*[@role="banner"]',
    '//*[@role="contentinfo"]',
)

_SEMANTIC_CONTENT_XPATHS = ("//article", "//main", '//*[@role="main"]')

# Minimum text chars for readability output to be considered useful.
_MIN_CONTENT_CHARS = 200


def _text_length(html: str) -> int:
    """Return the approximate length of visible text in an HTML fragment."""
    if not html or not html.strip():
        return 0
    return len(_TAG_RE.sub("", html).strip())


def _strip_boilerplate(tree) -> None:
    """Remove boilerplate elements from an lxml tree in-place."""
    for xpath in _BOILERPLATE_XPATHS:
        for el in tree.xpath(xpath):
            p = el.getparent()
            if p is not None:
                p.remove(el)


def _serialize_body(tree) -> str:
    """Serialize the <body> (or root) of an lxml tree to HTML."""
    body = tree.xpath("//body")
    return lxml_html.tostring(body[0] if body else tree, encoding="unicode")


def _body_fallback(html: str) -> str:
    """Lightweight fallback: strip boilerplate elements, return body HTML."""
    try:
        tree = lxml_html.fromstring(html)
        _strip_boilerplate(tree)
        return _serialize_body(tree)
    except Exception:
        return ""


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

    # Parse HTML once — reuse for metadata, readability, and fallback
    tree = None
    try:
        tree = lxml_html.fromstring(html)
    except Exception:
        pass

    # Metadata + title fallback — extract BEFORE any tree mutations
    description = ""
    language = ""
    fallback_title = ""
    if tree is not None:
        try:
            desc_els = tree.xpath('//meta[@name="description"]/@content')
            if desc_els:
                description = desc_els[0]
            lang_els = tree.xpath("//html/@lang")
            if lang_els:
                language = lang_els[0]
            title_els = tree.xpath("//title/text()")
            if title_els:
                fallback_title = title_els[0].strip()
        except Exception:
            pass

    content_html = ""
    title = ""

    if tree is not None:
        # Strip boilerplate once — shared between all extraction paths
        _strip_boilerplate(tree)

        # Fast path: semantic HTML tags (<main>, role="main", single <article>)
        for xpath in _SEMANTIC_CONTENT_XPATHS:
            els = tree.xpath(xpath)
            # For <article>, only use fast path if there's exactly one —
            # multiple <article> tags usually mean card/list items, not main content
            if els and (xpath != "//article" or len(els) == 1):
                candidate = lxml_html.tostring(els[0], encoding="unicode")
                if _text_length(candidate) >= _MIN_CONTENT_CHARS:
                    content_html = candidate
                    break

        # Standard path: readability on the pre-stripped tree (smaller DOM = faster)
        # retry_length=0: skip the expensive lenient-mode retry when ruthless
        # mode finds a short article — our own fallback handles that case.
        if not content_html:
            try:
                doc = ReadabilityDocument(tree, url=url or None, retry_length=0)
                content_html = doc.summary()
                # Skip doc.short_title() — it triggers another _parse()+clean_html
                # pass (~13ms). We already have fallback_title from <title> tag.
            except Exception:
                logger.warning("readability_failed", url=url, exc_info=True)

        # Fallback: reuse already-stripped tree body (no re-parse)
        if _text_length(content_html) < _MIN_CONTENT_CHARS:
            body_html = _serialize_body(tree)
            if _text_length(body_html) >= _MIN_CONTENT_CHARS:
                content_html = body_html
            else:
                # Last resort: trafilatura on original HTML (~100-170ms)
                try:
                    import trafilatura

                    content_html = trafilatura.extract(
                        html,
                        url=url or None,
                        output_format="html",
                        include_tables=True,
                        include_links=True,
                        include_formatting=True,
                        favor_recall=True,
                    ) or content_html
                except Exception:
                    pass

    # Use readability's title, fall back to raw <title> tag
    if not title:
        title = fallback_title

    # Post-process: word count threshold
    if word_count_threshold and word_count_threshold > 0:
        content_html = _apply_word_count_threshold(content_html, word_count_threshold)

    # Post-process: content filters
    if content_filter:
        content_html = _apply_content_filter(
            content_html, content_filter, content_filter_query
        )

    return CleanedContent(
        title=title,
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

    soup = make_soup(html)

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
    soup = make_soup(html)

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


