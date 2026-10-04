"""Native YouTube transcript extraction via the caption (timedtext) track.

No audio download, no ffmpeg, no Whisper: fetch the watch page, read the player
response's ``captionTracks``, then fetch and parse that track's timedtext XML.
"""

from __future__ import annotations

import html
import re

import structlog

from pawgrab.engine.reader_http import reader_get
from pawgrab.utils.xmlsafe import safe_fromstring

logger = structlog.get_logger()
_YT_HOSTS = ("youtube.com", "youtu.be")
_CONSENT_COOKIE = {"CONSENT": "YES+1"}
_VIDEO_ID_RES = (
    re.compile(r"(?:v=|/shorts/|/embed/|/live/)([0-9A-Za-z_-]{11})"),
    re.compile(r"youtu\.be/([0-9A-Za-z_-]{11})"),
)


def extract_video_id(url: str) -> str | None:
    """Pull the 11-char video id from any watch/shorts/embed/youtu.be URL."""
    for pat in _VIDEO_ID_RES:
        m = pat.search(url)
        if m:
            return m.group(1)
    return None


def _extract_json_object(text: str, marker: str) -> str | None:
    """Return the brace-balanced JSON object that follows ``marker`` in ``text``."""
    start = text.find(marker)
    if start == -1:
        return None
    start = text.find("{", start)
    if start == -1:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _pick_track(tracks: list[dict], languages: list[str] | None) -> dict | None:
    """Choose a caption track: requested language first, manual over auto-generated (asr)."""
    if not tracks:
        return None
    ordered = sorted(tracks, key=lambda t: t.get("kind") == "asr")
    if languages:
        for lang in languages:
            for t in ordered:
                if t.get("languageCode", "").startswith(lang):
                    return t
    return ordered[0]


def _parse_timedtext(xml_text: str) -> list[dict]:
    """Parse timedtext ``<text start= dur=>`` entries into segments."""
    root = safe_fromstring(xml_text)
    segments: list[dict] = []
    for node in root.findall("text"):
        raw = node.text or ""
        if not raw.strip():
            continue
        segments.append(
            {
                "start": round(float(node.get("start", 0.0)), 3),
                "duration": round(float(node.get("dur", 0.0)), 3),
                "text": html.unescape(raw).replace("\n", " ").strip(),
            }
        )
    return segments


async def fetch_transcript(url: str, *, languages: list[str] | None = None) -> dict:
    """Fetch a YouTube transcript. Returns video_id, title, language, segments, and joined text.

    Sends a ``CONSENT`` cookie to skip YouTube's EU consent interstitial, which
    otherwise hides the player response. Raises ``ValueError`` when the URL is
    not a video or the video has no captions.
    """
    import orjson

    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError("not a recognizable YouTube video URL")
    resp = await reader_get(f"https://www.youtube.com/watch?v={video_id}", cookies=_CONSENT_COOKIE)
    if resp.status_code != 200:
        raise ValueError(f"YouTube returned HTTP {resp.status_code}")
    player_raw = _extract_json_object(resp.text, "ytInitialPlayerResponse")
    if not player_raw:
        raise ValueError("could not read YouTube player response (video unavailable or blocked)")
    player = orjson.loads(player_raw)
    tracks = player.get("captions", {}).get("playerCaptionsTracklistRenderer", {}).get("captionTracks", [])
    track = _pick_track(tracks, languages)
    if not track or not track.get("baseUrl"):
        raise ValueError("no captions available for this video")
    cap_resp = await reader_get(track["baseUrl"])
    if cap_resp.status_code != 200:
        raise ValueError(f"caption track returned HTTP {cap_resp.status_code}")
    segments = _parse_timedtext(cap_resp.text)
    if not segments:
        raise ValueError("caption track was empty")
    return {
        "video_id": video_id,
        "title": player.get("videoDetails", {}).get("title"),
        "language": track.get("languageCode"),
        "auto_generated": track.get("kind") == "asr",
        "segments": segments,
        "text": " ".join(s["text"] for s in segments),
    }
