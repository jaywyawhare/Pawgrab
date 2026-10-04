"""Native Reddit reader via the public ``.json`` endpoint — no login, no API key.

A post URL yields the post plus a bounded comment tree; a subreddit or listing URL
yields its posts. Reddit serves this JSON to any browser-like client.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import structlog

from pawgrab.engine.reader_http import reader_get
from pawgrab.utils.url_safety import host_matches

logger = structlog.get_logger()
_MAX_COMMENTS = 200
_MAX_DEPTH = 6


def is_reddit(url: str) -> bool:
    return host_matches(url, "reddit.com", "redd.it")


def _json_url(url: str) -> str:
    """Append ``.json`` to the path (Reddit's public read endpoint), preserving the query."""
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or "/"
    if not path.endswith(".json"):
        path = f"{path}.json"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def _post(data: dict) -> dict:
    return {
        "id": data.get("id"),
        "title": data.get("title"),
        "author": data.get("author"),
        "subreddit": data.get("subreddit"),
        "selftext": data.get("selftext") or None,
        "url": data.get("url"),
        "permalink": f"https://www.reddit.com{data.get('permalink', '')}" if data.get("permalink") else None,
        "score": data.get("score"),
        "upvote_ratio": data.get("upvote_ratio"),
        "num_comments": data.get("num_comments"),
        "created_utc": data.get("created_utc"),
        "flair": data.get("link_flair_text"),
        "over_18": data.get("over_18"),
    }


def _comments(listing: dict, *, depth: int = 0, acc: list | None = None) -> list[dict]:
    """Flatten the comment forest into nested dicts, bounded by count and depth."""
    acc = [] if acc is None else acc
    for child in listing.get("data", {}).get("children", []):
        if len(acc) >= _MAX_COMMENTS or child.get("kind") != "t1":
            continue
        d = child.get("data", {})
        node = {
            "author": d.get("author"),
            "body": d.get("body"),
            "score": d.get("score"),
            "created_utc": d.get("created_utc"),
            "replies": [],
        }
        acc.append(node)
        replies = d.get("replies")
        if isinstance(replies, dict) and depth < _MAX_DEPTH:
            _comments(replies, depth=depth + 1, acc=node["replies"])
    return acc


async def fetch_reddit(url: str, *, limit: int = 50) -> dict:
    """Fetch a Reddit post (with comments) or a listing (posts). Raises ``ValueError`` on bad input."""
    resp = await reader_get(_json_url(url))
    if resp.status_code != 200:
        raise ValueError(f"Reddit returned HTTP {resp.status_code}")
    payload = resp.json()
    if isinstance(payload, list) and len(payload) == 2:
        children = payload[0].get("data", {}).get("children", [])
        if not children:
            raise ValueError("Reddit post not found")
        return {
            "kind": "post",
            "post": _post(children[0].get("data", {})),
            "comments": _comments(payload[1]),
        }
    if isinstance(payload, dict) and payload.get("kind") == "Listing":
        posts = [_post(c.get("data", {})) for c in payload.get("data", {}).get("children", []) if c.get("kind") == "t3"]
        return {"kind": "listing", "posts": posts[:limit]}
    raise ValueError("unrecognized Reddit response")
