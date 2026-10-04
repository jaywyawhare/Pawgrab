"""DTD-rejecting XML parse shared by the sitemap, feed, and transcript readers."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree

_DOCTYPE_RE = re.compile(r"<!DOCTYPE", re.IGNORECASE)


def safe_fromstring(xml_text: str):
    """Parse untrusted XML, rejecting DTDs to prevent entity-expansion (billion-laughs) DoS.

    Target sites supply arbitrary XML. defusedxml is used when available;
    otherwise any document declaring a DOCTYPE (the internal-entity-expansion
    vector) is refused before reaching the stdlib parser.
    """
    if _DOCTYPE_RE.search(xml_text[:4096]):
        raise ValueError("XML declares a DOCTYPE; refusing to parse (XXE/billion-laughs)")
    try:
        import defusedxml.ElementTree as DefusedET

        return DefusedET.fromstring(xml_text)
    except ImportError:
        return ElementTree.fromstring(xml_text)
