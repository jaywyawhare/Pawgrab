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
    "//script",
    "//style",
    "//noscript",
    "//svg",
    "//iframe",
    "//nav",
    # Page-level headers only — an in-article <header> usually holds the H1/byline,
    # so stripping every <header> would drop real content (recall loss).
    "//header[not(ancestor::article) and not(ancestor::main) and not(ancestor::*[@role='main'])]",
    "//footer",
    "//aside",
    "//form",
    '//*[@role="navigation"]',
    '//*[@role="banner"]',
    '//*[@role="contentinfo"]',
    '//*[@role="complementary"]',
    '//*[@role="search"]',
    '//*[@role="dialog"]',
    '//*[@role="alertdialog"]',
)

_SEMANTIC_CONTENT_XPATHS = ("//article", "//main", '//*[@role="main"]')

_MIN_CONTENT_CHARS = 200

# Tightly-scoped noise patterns: only clearly non-content elements.
# Deliberately excludes broad terms like "widget", "banner", "social", "share", "promo"
# that frequently appear in legitimate content class names.
_NOISE_CLASS_RE = re.compile(
    r"\b(?:"
    r"sidebar"
    r"|cookie[-_](?:banner|bar|consent|notice|popup)"
    r"|newsletter[-_](?:signup|form)"
    r"|pagination|pager\b"
    r"|breadcrumbs?"
    r"|read[-_]more|more[-_]stories|also[-_]read|related[-_](?:posts|articles|stories|content)"
    r"|nav[-_](?:menu|bar|links?)|menu[-_](?:item|list|nav)"
    # Comment sections (but not the content word "commentary")
    r"|comments?(?:[-_](?:list|section|area|wrap|respond|thread|box))?|disqus\w*"
    # Share / social widgets (anchored so "shareholder"/"social-context" prose is safe)
    r"|share[-_](?:bar|buttons?|links?|tools?|widget|this|sheet|count)"
    r"|social[-_](?:share|links?|bar|icons?|nav|media)"
    # Ad slots and promos
    r"|ad[-_](?:slot|unit|banner|container|wrapper|box)|advert(?:isement)?|sponsored"
    # Modals / overlays / popups
    r"|modal|popup|lightbox|overlay"
    r")\b",
    re.IGNORECASE,
)

# Markdown link-noise pattern: lines that are purely navigation links
_MD_LINK_LINE_RE = re.compile(r"^\s*(?:\[.+?\]\(.+?\)\s*[|·•\-]?\s*){3,}\s*$")
_MD_LINK_RE = re.compile(r"\[.+?\]\(.+?\)")


def _text_length(html: str) -> int:
    """Return the approximate length of visible text in an HTML fragment."""
    if not html or not html.strip():
        return 0
    return len(_TAG_RE.sub("", html).strip())


def _content_score(html: str) -> float:
    """Score an extraction candidate: visible text length discounted by link density.

    Rewards fuller extractions (recall) while penalising nav/link furniture, so a
    longer-but-cleaner candidate beats a short one and a link-dump loses to real
    prose of the same length. Used to pick between semantic, readability and
    trafilatura outputs instead of defaulting to whichever ran first.
    """
    tl = _text_length(html)
    if tl <= 0:
        return 0.0
    try:
        root = lxml_html.fromstring(html)
        link_text = sum(len((a.text_content() or "").strip()) for a in root.iter("a"))
    except Exception:
        link_text = 0
    density = min(link_text / tl, 1.0)
    return tl * (1.0 - 0.8 * density)


def _strip_boilerplate(tree) -> None:
    """Remove boilerplate elements from an lxml tree in-place."""
    for xpath in _BOILERPLATE_XPATHS:
        for el in tree.xpath(xpath):
            p = el.getparent()
            if p is not None:
                p.remove(el)


def _strip_noise_by_class(tree) -> None:
    """Remove elements whose class/id attributes match tightly-scoped noise patterns."""
    for el in list(tree.iter()):
        try:
            cls = el.get("class") or ""
            eid = el.get("id") or ""
            if _NOISE_CLASS_RE.search(cls) or _NOISE_CLASS_RE.search(eid):
                p = el.getparent()
                if p is not None:
                    p.remove(el)
        except Exception:
            pass


def _serialize_body(tree) -> str:
    """Serialize the <body> (or root) of an lxml tree to HTML."""
    body = tree.xpath("//body")
    return lxml_html.tostring(body[0] if body else tree, encoding="unicode")


# Block-level containers worth link-density testing. Excludes <article>/<main>
# (the content roots) and <table> (tables are content, not link furniture).
_PRUNABLE_TAGS = frozenset(
    {"div", "ul", "ol", "nav", "aside", "section", "header", "footer", "form", "p"}
)


def _prune_link_density(
    html: str, *, threshold: float = 0.5, min_text: int = 30
) -> str:
    """Drop blocks whose text is mostly anchor text (share bars, related lists, nav).

    Complements tag/class stripping by catching link furniture that carries no
    tell-tale class name. Guarded: if pruning would drop the result below the
    minimum content size it returns the input unchanged, so it can never nuke a
    legitimately link-heavy article down to nothing.
    """
    if not html or not html.strip():
        return html
    try:
        root = lxml_html.fromstring(html)
    except Exception:
        return html

    doomed = []
    for el in root.iter():
        if el is root or el.tag not in _PRUNABLE_TAGS:
            continue
        text = (el.text_content() or "").strip()
        if len(text) < min_text:
            continue
        link_text = sum(len((a.text_content() or "").strip()) for a in el.iter("a"))
        if link_text / len(text) > threshold:
            doomed.append(el)

    for el in doomed:
        parent = el.getparent()
        if parent is not None:  # None => already removed with an ancestor
            parent.remove(el)

    pruned = lxml_html.tostring(root, encoding="unicode")
    return pruned if _text_length(pruned) >= _MIN_CONTENT_CHARS else html


# Title separators: pipe, en/em dash, middot, bullet, and spaced hyphen.
_TITLE_SEP_RE = re.compile(r"\s+[|–—·•\-]\s+")


def _clean_title(raw: str) -> str:
    """Strip a trailing site-name segment (e.g. "Article | Site") from a title."""
    if not raw:
        return ""
    raw = raw.strip()
    parts = [p.strip() for p in _TITLE_SEP_RE.split(raw) if p.strip()]
    if len(parts) > 1:
        best = max(parts, key=len)
        if len(best) >= 10:
            return best
    return raw


def _merge_sections(tree) -> str:
    """Concatenate all top-level <section> / <article> blocks when no single container found."""
    for xpath in ("//article", "//section", "//main"):
        els = tree.xpath(xpath)
        if not els:
            continue
        blocks = []
        for el in els:
            try:
                s = lxml_html.tostring(el, encoding="unicode")
                if isinstance(s, str) and _text_length(s) > 50:
                    blocks.append(s)
            except Exception:
                pass
        if blocks:
            return "<div>" + "".join(blocks) + "</div>"
    return ""


# Accessibility/skip-nav text that often leaks into extracted content
_SKIP_NAV_RE = re.compile(
    r"^(?:skip\s+(?:to\s+)?(?:main\s+)?content|main\s+content\s*\+?\s*sidebar|jump\s+to\s+(?:main\s+)?content)\s*$",
    re.IGNORECASE,
)


def _filter_markdown_link_noise(markdown: str) -> str:
    """Remove nav-link lines, skip-nav text, and other structural noise."""
    if not markdown:
        return markdown
    lines = markdown.splitlines()
    kept = []
    for line in lines:
        stripped = line.strip()
        # Skip accessibility/skip-nav remnants
        if _SKIP_NAV_RE.match(stripped):
            continue
        # Skip lines that are 3+ consecutive markdown links (nav menus)
        if _MD_LINK_LINE_RE.match(line):
            continue
        # Skip short lines where >70% of words come from link anchors
        words = line.split()
        if len(words) >= 4:
            link_matches = _MD_LINK_RE.findall(line)
            link_word_count = sum(len(m.split()) for m in link_matches)
            if link_word_count / len(words) > 0.7:
                continue
        kept.append(line)
    # Collapse runs of 3+ blank lines left by removed lines
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(kept))
    return result.strip()


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

    html = _preprocess(html, excluded_tags, excluded_selector, css_selector)

    tree = None
    try:
        tree = lxml_html.fromstring(html)
    except Exception:
        pass

    description = ""
    language = ""
    fallback_title = ""
    og_title = ""
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
            og_els = tree.xpath('//meta[@property="og:title"]/@content')
            if og_els:
                og_title = og_els[0].strip()
        except Exception:
            pass

    content_html = ""
    title = ""

    if tree is not None:
        _strip_boilerplate(tree)
        try:
            _strip_noise_by_class(tree)
        except Exception:
            pass

        # Collect every viable extraction and pick the best by content score
        # (text length discounted by link density). Readability under-extracts on
        # product/listing/FAQ/docs layouts it doesn't recognise as "articles";
        # scoring lets a fuller trafilatura or semantic-container result win
        # instead of defaulting to whichever ran first.
        candidates: list[str] = []

        # Semantic containers (article/main/role=main). Run first: readability may
        # mutate `tree`, so snapshot these before invoking it. Add both the first
        # block and — when a page has several (a forum thread's posts, an item
        # grid) — their concatenation, so the score picks the fuller one instead of
        # a single post. Boilerplate merges lose on link density; real threads win.
        for xpath in _SEMANTIC_CONTENT_XPATHS:
            try:
                els = tree.xpath(xpath)
                if not els:
                    continue
                first = lxml_html.tostring(els[0], encoding="unicode")
                if _text_length(first) >= _MIN_CONTENT_CHARS:
                    candidates.append(first)
                if len(els) >= 3:
                    blocks = [lxml_html.tostring(e, encoding="unicode") for e in els]
                    lengths = [_text_length(b) for b in blocks]
                    total = sum(lengths)
                    # Merge only for a genuine thread / item grid: several blocks and
                    # no single one dominating. An article with a few related-post
                    # cards has one block holding most of the text, so it's excluded
                    # and keeps its clean single-article extraction (precision).
                    if total and max(lengths) / total < 0.45:
                        merged = "<div>" + "".join(
                            b for b, ln in zip(blocks, lengths) if ln > 30
                        ) + "</div>"
                        if _text_length(merged) >= _MIN_CONTENT_CHARS:
                            candidates.append(merged)
            except Exception:
                pass

        try:
            # retry_length is readability's lenient-retry threshold; keeping the
            # library default (250) lets it recover short articles that a strict
            # pass would drop to the low-precision body fallback.
            doc = ReadabilityDocument(tree, url=url or None, retry_length=250)
            rr = doc.summary() or ""
            if _text_length(rr) >= _MIN_CONTENT_CHARS:
                candidates.append(rr)
        except Exception:
            logger.warning("readability_failed", url=url, exc_info=True)

        try:
            import trafilatura

            traf_html = trafilatura.extract(
                html,
                url=url or None,
                output_format="html",
                include_tables=True,
                include_links=True,
                include_formatting=True,
                favor_recall=True,
                no_fallback=False,
            ) or ""
            if _text_length(traf_html) >= _MIN_CONTENT_CHARS:
                candidates.append(traf_html)
        except Exception:
            pass

        if candidates:
            content_html = max(candidates, key=_content_score)

        # Last resort before body fallback: merge article/section blocks.
        # Only used when the primary extractors found nothing — avoids overriding
        # good single-article extraction with noisy multi-card merges.
        if not content_html:
            try:
                merged = _merge_sections(tree)
                if merged and _text_length(merged) >= _MIN_CONTENT_CHARS:
                    content_html = merged
            except Exception:
                pass

        # Fallback: full body with boilerplate stripped
        if _text_length(content_html) < _MIN_CONTENT_CHARS:
            body_html = _serialize_body(tree)
            if body_html:
                content_html = body_html

        # Precision pass: drop link-dominated blocks (share bars, related-post
        # lists, nav remnants) that survive tag/class stripping. Applied to every
        # extraction source, including the whole-body fallback.
        if content_html:
            try:
                content_html = _prune_link_density(content_html)
            except Exception:
                pass

    if not title:
        title = _clean_title(og_title or fallback_title)
        if not title and tree is not None:
            try:
                h1 = "".join(tree.xpath("//h1//text()")).strip()
                if h1:
                    title = h1
            except Exception:
                pass
        if not title:
            title = fallback_title

    if word_count_threshold and word_count_threshold > 0:
        content_html = _apply_word_count_threshold(content_html, word_count_threshold)

    if content_filter:
        content_html = _apply_content_filter(content_html, content_filter, content_filter_query)

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

    if excluded_tags:
        for tag_name in excluded_tags:
            for el in soup.find_all(tag_name.lower()):
                el.decompose()

    if excluded_selector:
        for el in soup.select(excluded_selector):
            el.decompose()

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
