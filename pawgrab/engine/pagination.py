"""Next-page detection for stitching multi-page articles/listings.

Many articles and listings split a single logical document across numbered pages.
``find_next_url`` locates the "next page" link so the scrape path can stitch the
bodies together into one result. Detection order (most to least reliable):

  1. ``<link rel="next">`` in <head> — the canonical signal.
  2. ``<a rel="next">`` anywhere in the body.
  3. An anchor whose visible text / aria-label is a next-page affordance
     ("next", "next page", "›", "»", "older posts"), excluding "next" that is
     clearly something else (e.g. "next day").
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from pawgrab.utils.text import make_soup

_NEXT_TEXT_RE = re.compile(
    r"^\s*[‹«]?\s*(?:next(?:\s+page)?|older(?:\s+posts?)?|more)\s*[›»→>]*\s*$" r"|^\s*(?:›|»|→|>>)\s*$",
    re.IGNORECASE,
)


def find_next_url(html: str, base_url: str) -> str | None:
    """Return the absolute URL of the next page, or None if there isn't one."""
    if not html or not html.strip():
        return None
    try:
        soup = make_soup(html)
    except Exception:
        return None

    # 1 & 2: explicit rel="next" (link or anchor).
    for tag_name in ("link", "a"):
        for tag in soup.find_all(tag_name):
            rel = tag.get("rel")
            rel_vals = rel if isinstance(rel, list) else [rel] if rel else []
            if any((r or "").lower() == "next" for r in rel_vals):
                href = tag.get("href")
                if href:
                    return urljoin(base_url, href)

    # 3: anchor text / aria-label affordance.
    for a in soup.find_all("a", href=True):
        label = (a.get("aria-label") or a.get_text() or "").strip()
        if _NEXT_TEXT_RE.match(label):
            href = a["href"]
            if href and not href.startswith("#"):
                return urljoin(base_url, href)
    return None
