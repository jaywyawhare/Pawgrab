"""Extract images, videos, audio, and links from HTML."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from pawgrab.utils.text import make_soup


def extract_all_media(html: str, base_url: str = "") -> dict[str, Any]:
    soup = make_soup(html)

    return {
        "images": _extract_images(soup, base_url),
        "videos": _extract_videos(soup, base_url),
        "audio": _extract_audio(soup, base_url),
        "links": _extract_links(soup, base_url),
    }


def _extract_images(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
    """Extract all images with metadata."""
    images = []
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if not src:
            # Try data-src (lazy loading) or srcset
            src = img.get("data-src", "") or img.get("data-lazy-src", "")
        if not src:
            continue

        image = {
            "src": urljoin(base_url, src) if base_url else src,
            "alt": img.get("alt", ""),
            "title": img.get("title", ""),
        }
        if img.get("width"):
            image["width"] = img["width"]
        if img.get("height"):
            image["height"] = img["height"]
        if img.get("srcset"):
            image["srcset"] = img["srcset"]

        images.append(image)

    # Also extract background images from style attributes
    for el in soup.find_all(style=True):
        style = el.get("style", "")
        if "url(" in style:
            urls = re.findall(r'url\(["\']?([^"\')\s]+)["\']?\)', style)
            for u in urls:
                images.append({
                    "src": urljoin(base_url, u) if base_url else u,
                    "alt": "",
                    "title": "",
                    "source": "css-background",
                })

    return images


def _extract_videos(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
    """Extract all video elements."""
    videos = []

    # HTML5 <video> elements
    for video in soup.find_all("video"):
        sources = []
        for source in video.find_all("source"):
            src = source.get("src", "")
            if src:
                sources.append({
                    "src": urljoin(base_url, src) if base_url else src,
                    "type": source.get("type", ""),
                })
        # Direct src on video tag
        src = video.get("src", "")
        if src:
            sources.append({
                "src": urljoin(base_url, src) if base_url else src,
                "type": "",
            })
        if sources:
            videos.append({
                "sources": sources,
                "poster": urljoin(base_url, video.get("poster", "")) if video.get("poster") else None,
                "width": video.get("width"),
                "height": video.get("height"),
            })

    # Embedded iframes (YouTube, Vimeo, etc.)
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src", "")
        if any(domain in src for domain in ("youtube", "vimeo", "dailymotion", "wistia")):
            videos.append({
                "sources": [{"src": src, "type": "embed"}],
                "width": iframe.get("width"),
                "height": iframe.get("height"),
                "embed": True,
            })

    return videos


def _extract_audio(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
    """Extract all audio elements."""
    audios = []

    for audio in soup.find_all("audio"):
        sources = []
        for source in audio.find_all("source"):
            src = source.get("src", "")
            if src:
                sources.append({
                    "src": urljoin(base_url, src) if base_url else src,
                    "type": source.get("type", ""),
                })
        src = audio.get("src", "")
        if src:
            sources.append({
                "src": urljoin(base_url, src) if base_url else src,
                "type": "",
            })
        if sources:
            audios.append({"sources": sources})

    return audios


def _extract_links(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
    """Extract all links with anchor text and attributes."""
    links = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue

        link = {
            "href": urljoin(base_url, href) if base_url else href,
            "text": a.get_text(strip=True),
            "title": a.get("title", ""),
        }
        if a.get("rel"):
            link["rel"] = " ".join(a.get("rel", []))
        if a.get("target"):
            link["target"] = a["target"]

        links.append(link)

    return links
