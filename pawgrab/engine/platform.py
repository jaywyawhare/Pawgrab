"""Classify a URL to the structured reader that fits it, else fall back to generic scrape."""

from __future__ import annotations

from urllib.parse import urlparse

from pawgrab.engine.github import parse_repo
from pawgrab.engine.reddit import is_reddit
from pawgrab.engine.transcript import _YT_HOSTS, extract_video_id
from pawgrab.utils.url_safety import host_matches

_FEED_HINTS = ("/feed", "/rss", "/atom")
_FEED_SUFFIXES = (".rss", ".atom", ".xml")


def _is_youtube_video(url: str) -> bool:
    return host_matches(url, *_YT_HOSTS) and extract_video_id(url) is not None


def _is_feed(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(_FEED_SUFFIXES) or any(h in path for h in _FEED_HINTS)


def detect_platform(url: str) -> str:
    """Return ``"youtube"``, ``"reddit"``, ``"github"``, ``"feed"``, or ``"web"`` for the given URL."""
    if _is_youtube_video(url):
        return "youtube"
    if is_reddit(url):
        return "reddit"
    if parse_repo(url) is not None:
        return "github"
    if _is_feed(url):
        return "feed"
    return "web"
