"""Content extraction via Readability."""

from __future__ import annotations

import json
import re

import structlog
from bs4 import BeautifulSoup
from lxml import html as lxml_html
from readability import Document as ReadabilityDocument

from pawgrab.utils.text import make_soup

logger = structlog.get_logger()


class CleanedContent:
    __slots__ = ("title", "content_html", "description", "language", "author", "publish_date")

    def __init__(
        self,
        title: str,
        content_html: str,
        description: str = "",
        language: str = "",
        author: str = "",
        publish_date: str = "",
    ):
        self.title = title
        self.content_html = content_html
        self.description = description
        self.language = language
        self.author = author
        self.publish_date = publish_date


_TAG_RE = re.compile(r"<[^>]+>")
_BOILERPLATE_XPATHS = (
    "//script",
    "//style",
    "//noscript",
    "//svg",
    "//iframe",
    "//nav",
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


_NOISE_CLASS_RE = re.compile(
    r"\b(?:"
    r"sidebar"
    r"|cookie[-_](?:banner|bar|consent|notice|popup)"
    r"|newsletter[-_](?:signup|form)"
    r"|pagination|pager\b"
    r"|breadcrumbs?"
    r"|read[-_]more|more[-_]stories|also[-_]read|related[-_](?:posts|articles|stories|content)"
    r"|nav[-_](?:menu|bar|links?)|menu[-_](?:item|list|nav)"
    r"|comments?(?:[-_](?:list|section|area|wrap|respond|thread|box))?|disqus\w*"
    r"|share[-_](?:bar|buttons?|links?|tools?|widget|this|sheet|count)"
    r"|social[-_](?:share|links?|bar|icons?|nav|media)"
    r"|ad[-_](?:slot|unit|banner|container|wrapper|box)|advert(?:isement)?|sponsored"
    r"|modal|popup|lightbox|overlay"
    # commerce furniture: recommendations, cross-sells, promo strips
    r"|related[-_](?:products?|items?|swatches?)"
    r"|(?:you[-_]|also[-_]?)?(?:may[-_])?also[-_](?:like|bought|viewed|purchased)"
    r"|recommend(?:ed|ations?)[-_]?(?:products?|items?|for[-_]you)?"
    r"|upsell|cross[-_]sell|(?:cross|up)[-_]selling"
    r"|recently[-_]viewed|recently[-_]browsed"
    r"|product[-_](?:grid|carousel|slider|rail|row|list-item)"
    r"|(?:promo|marketing|hero)[-_](?:banner|bar|strip|tile|card)"
    r"|announcement[-_]?bar"
    r"|size[-_]?guide|trust[-_](?:badges?|pilot|seal)"
    r")\b",
    re.IGNORECASE,
)

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


_JSONLD_BODY_KEYS = ("articleBody", "reviewBody", "description", "text")
_JSONLD_CONTENT_TYPES = frozenset(
    {
        "Article",
        "NewsArticle",
        "BlogPosting",
        "Report",
        "TechArticle",
        "Product",
        "Recipe",
        "QAPage",
        "Question",
    }
)


def _iter_jsonld_objects(html: str):
    """Yield each JSON-LD object embedded in the page (handles @graph and arrays)."""
    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        raw = match.group(1).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                if "@graph" in node and isinstance(node["@graph"], list):
                    stack.extend(node["@graph"])
                yield node


def _jsonld_content_html(html: str) -> str:
    """Build an HTML content candidate from JSON-LD article/product/recipe bodies.

    Most modern CMS/e-commerce pages embed the clean article body or product
    description in schema.org JSON-LD. It is deterministic, boilerplate-free, and
    exactly the high-precision source readability under-extracts on product/FAQ/
    recipe layouts — added here as a *scored* candidate so it only wins when it is
    genuinely the fullest clean extraction.
    """
    if "ld+json" not in html.lower():
        return ""
    best = ""
    for node in _iter_jsonld_objects(html):
        types = node.get("@type", "")
        types = types if isinstance(types, list) else [types]
        if not any(t in _JSONLD_CONTENT_TYPES for t in types):
            continue
        for key in _JSONLD_BODY_KEYS:
            val = node.get(key)
            if isinstance(val, str) and len(val.strip()) > len(best):
                best = val.strip()
    if len(best) < _MIN_CONTENT_CHARS:
        return ""

    paras = [p.strip() for p in re.split(r"\n{2,}|\r\n\r\n", best) if p.strip()]
    if not paras:
        paras = [best]
    from html import escape

    return "<div>" + "".join(f"<p>{escape(p)}</p>" for p in paras) + "</div>"


_WRAPPER_TAG_PREFIXES = ("//header", "//footer", "//aside", "//form")


def _strip_boilerplate(tree) -> None:
    """Remove boilerplate elements from an lxml tree in-place.

    Wrapper tags get a large-share guard: some templates wrap nearly the whole
    document in a ``<header>``/``<form>``, and unconditional removal deletes the
    real content along with the chrome.
    """
    body = tree.xpath("//body")
    total = len(body[0].text_content() or "") if body else 0
    for xpath in _BOILERPLATE_XPATHS:
        guarded = xpath.startswith(_WRAPPER_TAG_PREFIXES)
        for el in tree.xpath(xpath):
            p = el.getparent()
            if p is None:
                continue
            if guarded and total and len(el.text_content() or "") > 0.6 * total:
                continue
            p.remove(el)


def _strip_noise_by_class(tree) -> None:
    """Remove elements whose class/id attributes match tightly-scoped noise patterns.

    Guards against page-killing false positives: structural roots are never
    removed, and neither is an element holding a large share of the remaining
    text — auto-generated CSS classes (e.g. Squarespace's ``collection-…`` on
    <body>) routinely collide with noise patterns while wrapping real content.
    """
    total = 0
    try:
        body = tree.xpath("//body")
        if body:
            total = len(body[0].text_content() or "")
    except Exception:
        pass
    limit = max(total * 0.4, 2000)
    for el in list(tree.iter()):
        try:
            if el.tag in ("html", "body"):
                continue
            cls = el.get("class") or ""
            eid = el.get("id") or ""
            if _NOISE_CLASS_RE.search(cls) or _NOISE_CLASS_RE.search(eid):
                if len(el.text_content() or "") > limit:
                    continue
                p = el.getparent()
                if p is not None:
                    p.remove(el)
        except Exception:
            pass


_ICON_FONT_TOKEN_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+){1,3}$", re.I)


def _strip_icon_font_junk(tree) -> None:
    """Remove elements whose text is dominated by icon-font ligature names.

    Icon fonts (e.g. Zalando's ``heart_outlined``) render their glyph names as
    visible text, one per product tile — thousands of junk tokens that no
    class/structure rule catches. A leaf element whose words are mostly
    snake_case tokens is a glyph run, never prose (real snake_case prose is
    vanishingly rare and lives in <code>, which is exempt).
    """
    for el in list(tree.iter()):
        if el.tag in ("code", "pre", "script", "style"):
            continue
        if el.xpath(".//p | .//div | .//section | .//article | .//li | .//td"):
            continue
        words = (el.text_content() or "").split()
        if len(words) < 4:
            continue
        junky = sum(1 for w in words if _ICON_FONT_TOKEN_RE.match(w))
        if junky / len(words) > 0.6:
            p = el.getparent()
            if p is not None:
                p.remove(el)


def _serialize_body(tree) -> str:
    """Serialize the <body> (or root) of an lxml tree to HTML."""
    body = tree.xpath("//body")
    return lxml_html.tostring(body[0] if body else tree, encoding="unicode")


_CAROUSEL_HEADING_RE = re.compile(
    r"^(?:people\s+who\s+viewed.*(?:also\s+)?viewed|you\s+may\s+(?:also\s+)?like|"
    r"customers?\s+also\s+(?:viewed|bought|shopped)|related\s+products?|"
    r"more\s+from\s+this\s+(?:collection|category)|recently\s+viewed)\b",
    re.I,
)


def _strip_commerce_furniture(tree) -> None:
    """Remove broken-theme config dumps and recommendation carousels.

    - Form controls (<select>/<option>) render their option lists as text but
      are pure UI (sort dropdowns, quantity pickers).
    - <dt>/<dd> pairs whose value is a bare URL are internal theme config that
      some stores render into the visible DOM (thousands of junk tokens).
    - A heading announcing a recommendations carousel is followed by a block of
      unrelated products; the heading's next element sibling is removed.
    """
    for el in list(tree.iter("select", "option", "datalist")):
        p = el.getparent()
        if p is not None:
            p.remove(el)
    for el in list(tree.iter("dt", "dd")):
        try:
            if re.fullmatch(r"(?:https?://\S+|[\w./\\-]+\.(?:jpg|png|webp|gif|svg)\S*)", (el.text_content() or "").strip()):
                p = el.getparent()
                if p is not None:
                    p.remove(el)
        except Exception:
            pass

    for h in tree.iter("h1", "h2", "h3", "h4", "strong", "b", "span", "p"):
        try:
            if not _CAROUSEL_HEADING_RE.match((h.text_content() or "").strip()):
                continue
        except Exception:
            continue
        node = h.getnext()
        hops = 0
        while node is not None and hops < 4:
            nxt = node.getnext()
            if node.tag not in ("div", "ul", "ol", "section"):
                node = nxt
                hops += 1
                continue
            text = node.text_content() or ""
            if len(text) > 200:
                # Carousels are walls of product links; a content grid with
                # real prose under the same heading must survive.
                link_text = sum(len((a.text_content() or "").strip()) for a in node.iter("a"))
                if text and link_text / len(text) > 0.35:
                    p = node.getparent()
                    if p is not None:
                        p.remove(node)
            break


_PRUNABLE_TAGS = frozenset({"div", "ul", "ol", "nav", "aside", "section", "header", "footer", "form", "p"})


_UI_CHROME_TAGS = frozenset({"a", "button", "span", "li", "p", "div", "small", "time", "label", "strong", "em", "b"})

_UI_CHROME_FULL_RE = re.compile(
    r"^(?:"
    r"add to (?:cart|bag|compare|wishlist|list|quote|favou?rites)"
    r"|quick\s*(?:view|shop|add|look)|buy(?: it)? now|shop now|pre-?order"
    r"|in stock|out of stock|low stock|sold out|view (?:details|more|all|product)"
    r"|load(?:ing)?(?: more)?\.{0,3}|show more|see (?:more|all|details)|read more"
    r"|try again|refresh|reset|clear(?: all| filters?)?|back(?: to top)?|top"
    r"|next|previous|prev|more|expand|collapse|reply|quote|report|share|save"
    r"|follow(?:ing)?|upvote|downvote|like|flag|edit|delete|subscribe"
    r"|sort by|filter|compare|wishlist|favou?rite"
    r"|click to expand|last seen|add to compare|quick view|view cart"
    r"|learn more|view (?:our|all) \w+|shop (?:all|now|by)|explore \w+"
    r"|customer reviews?|write a review|read reviews?|\d+ reviews?"
    r"|related products?|you may also like|recently viewed"
    r"|free shipping(?: [\w ]{0,20})?|satisfaction guaranteed"
    r")[\s:•·|>-]*$",
    re.I,
)

_UI_CHROME_PART_RE = re.compile(
    r"(?:"
    r"\b\d[\d,]* (?:posts?|replies|reviews?|badges?|followers?|points?|reputation|answers?|votes?)\b"
    r"|\b(?:bronze|silver|gold) badges?\b|\b\d+ (?:bronze|silver|gold)\b"
    r"|\bmember since\b|\bjoined \w+ ?\d*\b|\b(?:edited|answered|asked|posted|commented|updated) \w+ \d"
    r"|\b(?:regular|sale|original|list|starting|was) price\b|\byou may also like\b"
    r"|\bcustomers? also\b|\bfree (?:shipping|delivery)\b|\badd to cart\b|\bprice:?\s*\$"
    r")",
    re.I,
)


def _strip_ui_chrome(html: str) -> str:
    """Drop short leaf blocks that are page-type UI chrome, not content.

    Only touches blocks with <= 8 words of *total* text, so it can never remove a
    real paragraph or a content container (whose text_content is long). Guarded to
    return the input unchanged if it would drop below the minimum content size.
    """
    if not html or not html.strip():
        return html
    try:
        root = lxml_html.fromstring(html)
    except Exception:
        return html
    doomed = []
    for el in root.iter():
        if el is root or el.tag not in _UI_CHROME_TAGS:
            continue
        text = (el.text_content() or "").strip()
        if not text or len(text.split()) > 8:
            continue
        low = text.lower()
        if _UI_CHROME_FULL_RE.match(low) or _UI_CHROME_PART_RE.search(low):
            doomed.append(el)
    for el in doomed:
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
    pruned = lxml_html.tostring(root, encoding="unicode")
    return pruned if _text_length(pruned) >= _MIN_CONTENT_CHARS else html


def _collapse_duplicate_blocks(html: str, *, min_words: int = 15) -> str:
    """Drop exact repeated content blocks (desktop/mobile theme duplication).

    E-commerce templates frequently render the same description/details twice
    (or 4×). Deduplication happens at the *leaf-block* level — an element
    containing no further block-level children — so a wrapper whose only child
    is one paragraph can never shadow that paragraph as a false "duplicate".
    Short blocks are left alone since legit repeats live there.
    """
    if not html or not html.strip():
        return html
    try:
        root = lxml_html.fromstring(html)
    except Exception:
        return html
    seen = set()
    doomed = []
    for el in root.iter("p", "li", "dd", "dt", "figcaption"):
        if el.xpath(".//p | .//div | .//section | .//article | .//ul | .//ol | .//table"):
            continue
        norm = re.sub(r"\s+", " ", el.text_content() or "").strip().lower()
        if len(norm.split()) < min_words:
            continue
        if norm in seen:
            doomed.append(el)
        else:
            seen.add(norm)
    for el in doomed:
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
    pruned = lxml_html.tostring(root, encoding="unicode")
    return pruned if _text_length(pruned) >= _MIN_CONTENT_CHARS else html


def _prune_link_density(html: str, *, threshold: float = 0.5, min_text: int = 30) -> str:
    """Drop blocks whose text is mostly anchor text (share bars, related lists, nav).

    Complements tag/class stripping by catching link furniture that carries no
    tell-tale class name. Two guards keep it from eating real content: if pruning
    would drop the result below the minimum content size, *or* below half of the
    input's text (card grids and topic listings are legitimately link-dense),
    the input is returned unchanged.
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
        if parent is not None:
            parent.remove(el)
    pruned = lxml_html.tostring(root, encoding="unicode")
    if _text_length(pruned) < _MIN_CONTENT_CHARS:
        return html
    if _text_length(pruned) < 0.5 * _text_length(html):
        return html
    return pruned


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


_DATE_META_XPATHS = (
    '//meta[@property="article:published_time"]/@content',
    '//meta[@itemprop="datePublished"]/@content',
    '//meta[@name="datePublished"]/@content',
    '//meta[@name="date"]/@content',
    '//meta[@property="og:published_time"]/@content',
    "//time[@datetime]/@datetime",
    "//time[@pubdate]/@datetime",
)
_AUTHOR_META_XPATHS = (
    '//meta[@name="author"]/@content',
    '//meta[@property="article:author"]/@content',
    '//meta[@name="twitter:creator"]/@content',
    '//*[@itemprop="author"]//*[@itemprop="name"]/text()',
    '//*[@rel="author"]/text()',
    '//*[contains(concat(" ", normalize-space(@class), " "), " author ")]//text()',
)


def _first_xpath(tree, xpaths) -> str:
    for xp in xpaths:
        try:
            vals = tree.xpath(xp)
        except Exception:
            continue
        for v in vals:
            s = (v or "").strip()
            if s:
                return s[:300]
    return ""


def _extract_byline(tree, html: str) -> tuple[str, str]:
    """Best-effort (author, publish_date) from JSON-LD, meta tags, and bylines."""
    author = publish_date = ""

    try:
        for script in tree.xpath('//script[@type="application/ld+json"]/text()'):
            try:
                data = json.loads(script)
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            if isinstance(data, dict) and isinstance(data.get("@graph"), list):
                items = data["@graph"]
            for it in items:
                if not isinstance(it, dict):
                    continue
                if not publish_date:
                    publish_date = str(it.get("datePublished") or it.get("dateCreated") or "").strip()
                if not author:
                    a = it.get("author")
                    if isinstance(a, dict):
                        author = str(a.get("name") or "").strip()
                    elif isinstance(a, list) and a and isinstance(a[0], dict):
                        author = str(a[0].get("name") or "").strip()
                    elif isinstance(a, str):
                        author = a.strip()
            if author and publish_date:
                break
    except Exception:
        pass
    if not publish_date:
        publish_date = _first_xpath(tree, _DATE_META_XPATHS)
    if not author:
        author = " ".join(_first_xpath(tree, _AUTHOR_META_XPATHS).split())
    return author[:300], publish_date[:100]


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

        if _SKIP_NAV_RE.match(stripped):
            continue

        if _MD_LINK_LINE_RE.match(line):
            continue

        words = line.split()
        if len(words) >= 4:
            link_matches = _MD_LINK_RE.findall(line)
            link_word_count = sum(len(m.split()) for m in link_matches)
            if link_word_count / len(words) > 0.7:
                continue
        kept.append(line)

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
    author = ""
    publish_date = ""
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
        try:
            author, publish_date = _extract_byline(tree, html)
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
        try:
            _strip_commerce_furniture(tree)
        except Exception:
            pass
        try:
            _strip_icon_font_junk(tree)
        except Exception:
            pass

        candidates: list[str] = []

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

                    if total and max(lengths) / total < 0.45:
                        merged = "<div>" + "".join(b for b, ln in zip(blocks, lengths, strict=False) if ln > 30) + "</div>"
                        if _text_length(merged) >= _MIN_CONTENT_CHARS:
                            candidates.append(merged)
            except Exception:
                pass
        try:
            doc = ReadabilityDocument(tree, url=url or None, retry_length=250)
            rr = doc.summary() or ""
            if _text_length(rr) >= _MIN_CONTENT_CHARS:
                candidates.append(rr)
        except Exception:
            logger.warning("readability_failed", url=url, exc_info=True)
        try:
            import trafilatura

            traf_html = (
                trafilatura.extract(
                    html,
                    url=url or None,
                    output_format="html",
                    include_tables=True,
                    include_links=True,
                    include_formatting=True,
                    favor_recall=True,
                    no_fallback=False,
                )
                or ""
            )
            if _text_length(traf_html) >= _MIN_CONTENT_CHARS:
                candidates.append(traf_html)
        except Exception:
            pass

        try:
            jsonld_html = _jsonld_content_html(html)
            if jsonld_html:
                candidates.append(jsonld_html)
        except Exception:
            pass
        if candidates:
            content_html = max(candidates, key=_content_score)
            # Every extractor collapsing to a small fragment while the stripped
            # body still holds far more text means all of them misfired on this
            # layout (product grids, forums, listing walls). Fall back to merged
            # sections and prefer them when they clearly capture more.
            body_len = _text_length(_serialize_body(tree))
            if body_len and _text_length(content_html) < body_len * 0.25:
                try:
                    merged = _merge_sections(tree)
                    if merged and _text_length(merged) > 1.5 * _text_length(content_html):
                        content_html = merged
                except Exception:
                    pass

        if not content_html:
            try:
                merged = _merge_sections(tree)
                if merged and _text_length(merged) >= _MIN_CONTENT_CHARS:
                    content_html = merged
            except Exception:
                pass

        if _text_length(content_html) < _MIN_CONTENT_CHARS:
            body_html = _serialize_body(tree)
            if body_html:
                content_html = body_html

        if content_html:
            try:
                content_html = _prune_link_density(content_html)
            except Exception:
                pass

            try:
                content_html = _strip_ui_chrome(content_html)
            except Exception:
                pass

            try:
                content_html = _collapse_duplicate_blocks(content_html)
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
        author=author,
        publish_date=publish_date,
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
        if not matches:
            for relaxed in _relaxed_selectors(css_selector):
                matches = soup.select(relaxed)
                if matches:
                    break
        if matches:
            new_soup = BeautifulSoup("<html><body></body></html>", "html.parser")
            body = new_soup.find("body")
            for match in matches:
                body.append(match.__copy__())
            return str(new_soup)
    return str(soup)


_PSEUDO_RE = re.compile(r"::?[a-zA-Z-]+(\([^)]*\))?")


def _relaxed_selectors(selector: str):
    """Yield progressively looser variants of *selector*, most specific first.
    Order: selector minus pseudo-classes → the deepest compound's classes/ids →
    its bare tag. The caller stops at the first variant that matches anything.
    """
    seen = {selector}

    def _fresh(candidate):
        candidate = (candidate or "").strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            yield candidate

    yield from _fresh(_PSEUDO_RE.sub("", selector).strip())

    compounds = re.split(r"[>+~\s]+", selector.strip())
    for compound in reversed(compounds):
        for match in re.findall(r"[.#][A-Za-z0-9_-]+", compound):
            yield from _fresh(match)
    for compound in reversed(compounds):
        tag_match = re.match(r"[a-zA-Z][a-zA-Z0-9-]*", compound)
        if tag_match and tag_match.group(0) not in ("html", "body"):
            yield from _fresh(tag_match.group(0))


def _apply_word_count_threshold(html: str, threshold: int) -> str:
    """Remove text blocks with fewer words than threshold."""
    soup = make_soup(html)
    for el in soup.find_all(["p", "li", "td", "th", "span", "div"]):
        text = el.get_text(strip=True)
        if text and len(text.split()) < threshold:
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
