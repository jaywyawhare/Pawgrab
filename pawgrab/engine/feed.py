"""Native RSS 2.0 / Atom feed reader — structured items, no third-party feed library."""

from __future__ import annotations

import html

import structlog

from pawgrab.engine.reader_http import reader_get
from pawgrab.utils.xmlsafe import safe_fromstring

logger = structlog.get_logger()
_ATOM_NS = "{http://www.w3.org/2005/Atom}"


def _text(node) -> str | None:
    """Return an element's unescaped, stripped text, or None when empty/absent."""
    if node is None or node.text is None:
        return None
    return html.unescape(node.text).strip() or None


def _atom_link(entry) -> str | None:
    """Atom entries carry <link href=...>; prefer rel=alternate, else the first href."""
    links = entry.findall(f"{_ATOM_NS}link")
    for link in links:
        if link.get("rel") in (None, "alternate") and link.get("href"):
            return link.get("href")
    return links[0].get("href") if links and links[0].get("href") else None


def _parse_atom(root, limit: int) -> dict:
    """Shape an Atom ``<feed>`` root into feed metadata plus up to ``limit`` entries."""
    items = []
    for entry in root.findall(f"{_ATOM_NS}entry")[:limit]:
        author = entry.find(f"{_ATOM_NS}author/{_ATOM_NS}name")
        items.append(
            {
                "title": _text(entry.find(f"{_ATOM_NS}title")),
                "link": _atom_link(entry),
                "published": _text(entry.find(f"{_ATOM_NS}published")) or _text(entry.find(f"{_ATOM_NS}updated")),
                "summary": _text(entry.find(f"{_ATOM_NS}summary")) or _text(entry.find(f"{_ATOM_NS}content")),
                "id": _text(entry.find(f"{_ATOM_NS}id")),
                "author": _text(author),
            }
        )
    return {
        "type": "atom",
        "title": _text(root.find(f"{_ATOM_NS}title")),
        "link": _atom_link(root),
        "description": _text(root.find(f"{_ATOM_NS}subtitle")),
        "items": items,
    }


def _parse_rss(root, limit: int) -> dict:
    """Shape an RSS 2.0 ``<rss>`` root into feed metadata plus up to ``limit`` items."""
    channel = root.find("channel")
    if channel is None:
        raise ValueError("RSS feed has no <channel>")
    dc = "{http://purl.org/dc/elements/1.1/}"
    items = []
    for item in channel.findall("item")[:limit]:
        items.append(
            {
                "title": _text(item.find("title")),
                "link": _text(item.find("link")),
                "published": _text(item.find("pubDate")),
                "summary": _text(item.find("description")),
                "id": _text(item.find("guid")),
                "author": _text(item.find("author")) or _text(item.find(f"{dc}creator")),
            }
        )
    return {
        "type": "rss",
        "title": _text(channel.find("title")),
        "link": _text(channel.find("link")),
        "description": _text(channel.find("description")),
        "items": items,
    }


async def fetch_feed(url: str, *, limit: int = 50) -> dict:
    """Fetch and parse an RSS 2.0 or Atom feed into feed metadata plus structured items.

    Raises ``ValueError`` when the document is not a recognizable feed.
    """
    resp = await reader_get(url)
    if resp.status_code != 200:
        raise ValueError(f"feed returned HTTP {resp.status_code}")
    root = safe_fromstring(resp.text)
    tag = root.tag.split("}")[-1].lower()
    if tag == "feed":
        feed = _parse_atom(root, limit)
    elif tag in ("rss", "rdf"):
        feed = _parse_rss(root, limit)
    else:
        raise ValueError(f"not an RSS or Atom feed (root <{tag}>)")
    feed["count"] = len(feed["items"])
    return feed
