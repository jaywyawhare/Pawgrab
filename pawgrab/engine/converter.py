"""HTML → Markdown / Text / JSON / CSV / XML conversion."""

from __future__ import annotations

import csv
import io
import math
import re

import orjson
import xml.etree.ElementTree as ET
from collections import Counter

import html2text
from bs4 import BeautifulSoup

from pawgrab.models.common import OutputFormat
from pawgrab.utils.text import make_soup, tokenize, word_count

# Reuse a single converter instance — HTML2Text is stateless between calls.
_md_converter = html2text.HTML2Text()
_md_converter.body_width = 0
_md_converter.ignore_links = False
_md_converter.ignore_images = False
_md_converter.protect_links = True
_md_converter.wrap_links = False


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


def html_to_markdown(html: str) -> str:
    return _md_converter.handle(html).strip()


def html_to_text(html: str) -> str:
    soup = make_soup(html)
    text = soup.get_text(separator="\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)


def html_to_json(html: str) -> str:
    """Convert HTML to a JSON structure of headings and paragraphs."""
    soup = make_soup(html)
    sections: list[dict] = []

    for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li"]):
        tag = el.name
        text = el.get_text(strip=True)
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
    soup = make_soup(html)

    tables = soup.find_all("table")
    buf = io.StringIO()
    writer = csv.writer(buf)

    if tables:
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["th", "td"])
                writer.writerow([c.get_text(strip=True) for c in cells])
            writer.writerow([])  # blank line between tables
    else:
        # Fallback: structured content as heading,content rows
        writer.writerow(["section", "content"])
        for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li"]):
            tag = el.name
            text = el.get_text(strip=True)
            if text:
                writer.writerow([tag, text])

    return buf.getvalue().strip()


def html_to_xml(html: str) -> str:
    """Convert HTML content to a structured XML document."""
    soup = make_soup(html)

    root = ET.Element("document")

    for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li"]):
        tag = el.name
        text = el.get_text(strip=True)
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

    # Keep top-k sections that meet the minimum score
    kept = [(idx, score, text) for idx, (text, score) in enumerate(scored) if score > min_score]
    kept = kept[:top_k]

    if not kept:
        return markdown

    # Re-sort by original position to maintain document order
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

    # Document frequency for IDF
    df: Counter[str] = Counter()
    for tokens in tokenized:
        for term in set(tokens):
            df[term] += 1

    results: list[tuple[str, float]] = []
    for section, tokens in zip(sections, tokenized):
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
