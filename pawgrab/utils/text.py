"""Shared text utilities."""

import re

from bs4 import BeautifulSoup


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric token extraction."""
    return re.findall(r"[a-z0-9]+", text.lower())


def word_count(text: str) -> int:
    return len(text.split())


def make_soup(html: str) -> BeautifulSoup:
    """Parse HTML with lxml, falling back to html.parser."""
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")
