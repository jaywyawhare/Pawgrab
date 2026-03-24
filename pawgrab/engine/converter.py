"""HTML → Markdown / Text / JSON / CSV / XML conversion."""

from __future__ import annotations

import csv
import io
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter

import orjson
from lxml import html as lxml_html

from pawgrab.models.common import OutputFormat
from pawgrab.utils.text import tokenize

_BLANK_COLLAPSE_RE = re.compile(r"\n{3,}")
_BLOCK_TAGS = frozenset({
    "p", "div", "section", "article", "main", "blockquote",
    "ul", "ol", "dl", "figure", "figcaption", "details", "summary",
    "table", "thead", "tbody", "tfoot", "tr",
})
_SKIP_TAGS = frozenset({"script", "style", "noscript", "svg", "template"})
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_LEAF_TAGS = frozenset({
    *_HEADING_TAGS, "a", "img", "li", "strong", "b",
    "em", "i", "code", "pre", "br", "hr", "td", "th",
})


def convert(html: str, fmt: OutputFormat) -> str:
    """Convert cleaned HTML content to the requested format."""
    match fmt:
        case OutputFormat.MARKDOWN:
            return html_to_markdown(html)
        case OutputFormat.TEXT:
            return html_to_text(html)
        case OutputFormat.HTML:
            return html
        case OutputFormat.JSON:
            return html_to_json(html)
        case OutputFormat.CSV:
            return html_to_csv(html)
        case OutputFormat.XML:
            return html_to_xml(html)


def html_to_markdown(html_str: str) -> str:
    """Convert HTML to Markdown via lxml tree walking (~10x faster than html2text)."""
    tree = lxml_html.fromstring(html_str)
    for el in tree.xpath("//script|//style|//noscript|//svg|//template"):
        if el.getparent() is not None:
            el.getparent().remove(el)

    parts: list[str] = []

    def _nl():
        """Append a newline only if the last part doesn't already end with one."""
        if parts and not parts[-1].endswith("\n"):
            parts.append("\n")

    def _walk(el):
        tag = el.tag if isinstance(el.tag, str) else ""
        if tag in _SKIP_TAGS:
            _emit_tail(el)
            return

        if tag in _HEADING_TAGS:
            t = el.text_content().strip()
            if t:
                _nl()
                parts.append(f"{'#' * int(tag[1])} {t}\n")
            _emit_tail(el)
            return

        if tag == "a":
            href = el.get("href", "")
            t = el.text_content().strip()
            if t and href:
                parts.append(f"[{t}]({href})")
            elif t:
                parts.append(t)
            _emit_tail(el)
            return

        if tag == "img":
            alt = el.get("alt", "")
            src = el.get("src", "")
            if src:
                parts.append(f"![{alt}]({src})")
            _emit_tail(el)
            return

        if tag == "li":
            _nl()
            t = el.text_content().strip()
            if t:
                parts.append(f"- {t}\n")
            _emit_tail(el)
            return

        if tag in ("strong", "b"):
            t = el.text_content().strip()
            if t:
                parts.append(f"**{t}**")
            _emit_tail(el)
            return

        if tag in ("em", "i"):
            t = el.text_content().strip()
            if t:
                parts.append(f"*{t}*")
            _emit_tail(el)
            return

        if tag == "code":
            t = el.text_content().strip()
            if t:
                parts.append(f"`{t}`")
            _emit_tail(el)
            return

        if tag == "pre":
            t = el.text_content()
            if t.strip():
                _nl()
                parts.append(f"```\n{t.strip()}\n```\n")
            _emit_tail(el)
            return

        if tag == "br":
            parts.append("\n")
            _emit_tail(el)
            return

        if tag == "hr":
            _nl()
            parts.append("---\n")
            _emit_tail(el)
            return

        if tag in ("td", "th"):
            t = el.text_content().strip()
            if t:
                parts.append(t)
            parts.append(" | ")
            _emit_tail(el)
            return

        if tag == "tr":
            parts.append("| ")
            for child in el:
                _walk(child)
            parts.append("\n")
            _emit_tail(el)
            return

        text = (el.text or "").strip()
        if tag == "blockquote":
            _nl()
            if text:
                parts.append(f"> {text} ")
        elif text:
            parts.append(text + " ")

        for child in el:
            _walk(child)

        if tag in _BLOCK_TAGS:
            _nl()

        _emit_tail(el)

    def _emit_tail(el):
        tail = (el.tail or "").strip()
        if tail:
            parts.append(" " + tail + " ")

    _walk(tree)
    md = "".join(parts)
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in md.splitlines())
    return _BLANK_COLLAPSE_RE.sub("\n\n", "\n".join(lines)).strip()


def html_to_text(html: str) -> str:
    tree = lxml_html.fromstring(html)
    text = tree.text_content()
    lines = (line.strip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def html_to_json(html: str) -> str:
    """Convert HTML to a JSON structure of headings and paragraphs."""
    tree = lxml_html.fromstring(html)
    sections: list[dict] = []

    for el in tree.iter("h1", "h2", "h3", "h4", "h5", "h6", "p", "li"):
        tag = el.tag
        text = (el.text_content() or "").strip()
        if not text:
            continue
        if tag.startswith("h"):
            sections.append({"heading": text, "level": int(tag[1]), "content": []})
        elif sections:
            sections[-1]["content"].append(text)
        else:
            sections.append({"heading": "", "level": 0, "content": [text]})

    return orjson.dumps(sections).decode()


def html_to_csv(html: str) -> str:
    """Extract tables from HTML and convert to CSV.

    If no tables are found, falls back to heading/content pairs.
    """
    tree = lxml_html.fromstring(html)

    buf = io.StringIO()
    writer = csv.writer(buf)
    tables = tree.xpath("//table")

    if tables:
        for table in tables:
            for row in table.xpath(".//tr"):
                cells = row.xpath(".//th|.//td")
                writer.writerow([(c.text_content() or "").strip() for c in cells])
            writer.writerow([])  # blank line between tables
    else:
        writer.writerow(["section", "content"])
        for el in tree.iter("h1", "h2", "h3", "h4", "h5", "h6", "p", "li"):
            tag = el.tag
            text = (el.text_content() or "").strip()
            if text:
                writer.writerow([tag, text])

    return buf.getvalue().strip()


def html_to_xml(html: str) -> str:
    """Convert HTML content to a structured XML document."""
    tree = lxml_html.fromstring(html)

    root = ET.Element("document")

    for el in tree.iter("h1", "h2", "h3", "h4", "h5", "h6", "p", "li"):
        tag = el.tag
        text = (el.text_content() or "").strip()
        if not text:
            continue
        child = ET.SubElement(root, tag)
        child.text = text

    return ET.tostring(root, encoding="unicode", xml_declaration=True)


_HEADING_RE = re.compile(r"^#{1,6}\s")
_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


def markdown_with_citations(markdown: str) -> str:
    """Convert inline markdown links to numbered citation-style references.

    Example:
        Input:  "See [Google](https://google.com) for details."
        Output: "See [Google][1] for details.\n\n[1]: https://google.com"
    """
    refs: list[str] = []
    url_to_idx: dict[str, int] = {}

    def _replace(m: re.Match) -> str:
        text, url = m.group(1), m.group(2)
        if url not in url_to_idx:
            url_to_idx[url] = len(refs) + 1
            refs.append(url)
        idx = url_to_idx[url]
        return f"[{text}][{idx}]"

    body = _LINK_RE.sub(_replace, markdown)
    if not refs:
        return body

    ref_section = "\n\n---\n\n**References**\n\n"
    ref_section += "\n".join(f"[{i + 1}]: {url}" for i, url in enumerate(refs))
    return body + ref_section


def fit_markdown(markdown: str, query: str, *, top_k: int = 5, min_score: float = 0.0) -> str:
    """Filter markdown sections by BM25 relevance to a query."""
    if not query or not markdown.strip():
        return markdown

    sections = _split_by_headings(markdown)
    if len(sections) <= 1:
        return markdown

    query_terms = tokenize(query)
    if not query_terms:
        return markdown

    scored = _bm25_score(sections, query_terms)
    scored.sort(key=lambda x: x[1], reverse=True)

    kept = [(idx, score, text) for idx, (text, score) in enumerate(scored) if score > min_score]
    kept = kept[:top_k]

    if not kept:
        return markdown

    kept.sort(key=lambda x: x[0])
    return "\n\n".join(text for _, _, text in kept)


def _split_by_headings(markdown: str) -> list[str]:
    """Split markdown into sections by heading boundaries."""
    lines = markdown.split("\n")
    sections: list[str] = []
    current: list[str] = []

    for line in lines:
        if _HEADING_RE.match(line) and current:
            sections.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)

    if current:
        sections.append("\n".join(current).strip())

    return [s for s in sections if s]


def _bm25_score(
    sections: list[str],
    query_terms: list[str],
    k1: float = 1.5,
    b: float = 0.75,
) -> list[tuple[str, float]]:
    """Score sections using Okapi BM25."""
    n = len(sections)
    tokenized = [tokenize(s) for s in sections]
    avg_dl = sum(len(t) for t in tokenized) / max(n, 1)

    df: Counter[str] = Counter()
    for tokens in tokenized:
        for term in set(tokens):
            df[term] += 1

    results: list[tuple[str, float]] = []
    for section, tokens in zip(sections, tokenized, strict=True):
        tf_map: Counter[str] = Counter(tokens)
        dl = len(tokens)
        score = 0.0

        for term in query_terms:
            if df[term] == 0:
                continue
            tf = tf_map[term]
            idf = math.log((n - df[term] + 0.5) / (df[term] + 0.5) + 1)
            numerator = tf * (k1 + 1)
            denominator = tf + k1 * (1 - b + b * dl / max(avg_dl, 1))
            score += idf * numerator / denominator

        results.append((section, score))

    return results
