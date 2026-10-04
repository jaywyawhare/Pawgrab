"""Tests for the capability doctor, YouTube transcript, RSS/Atom feed, Reddit, GitHub, and URL auto-routing."""

from unittest.mock import AsyncMock, patch

import pytest

from pawgrab.engine.diagnostics import run_diagnostics
from pawgrab.engine.feed import _parse_atom, _parse_rss
from pawgrab.engine.github import parse_repo
from pawgrab.engine.platform import detect_platform
from pawgrab.engine.reddit import _comments, _json_url, is_reddit
from pawgrab.engine.transcript import _extract_json_object, _parse_timedtext, _pick_track, extract_video_id
from pawgrab.utils.xmlsafe import safe_fromstring

# --- capability doctor ---


def test_doctor_shape_and_counts():
    report = run_diagnostics()
    assert report["status"] in ("ok", "degraded")
    assert set(report["capabilities"]) == {"fetch", "browser", "llm", "captcha", "proxies", "search", "storage"}
    assert report["summary"]["ok"] + report["summary"]["warn"] + report["summary"]["off"] == 7
    assert report["capabilities"]["fetch"]["status"] == "ok"


def test_doctor_llm_key_flips_to_ok(monkeypatch):
    from pawgrab.config import settings

    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "")
    assert run_diagnostics()["capabilities"]["llm"]["status"] == "off"
    monkeypatch.setattr(settings, "openai_api_key", "sk-x")
    assert run_diagnostics()["capabilities"]["llm"]["status"] == "ok"


def test_doctor_ollama_is_warn_not_ok(monkeypatch):
    from pawgrab.config import settings

    monkeypatch.setattr(settings, "llm_provider", "ollama")
    assert run_diagnostics()["capabilities"]["llm"]["status"] == "warn"


def test_doctor_s3_without_creds_degrades(monkeypatch):
    from pawgrab.config import settings

    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "s3_bucket", "")
    report = run_diagnostics()
    assert report["capabilities"]["storage"]["status"] == "warn"
    assert report["status"] == "degraded"


# --- platform detection ---


def test_detect_platform():
    assert detect_platform("https://youtu.be/dQw4w9WgXcQ") == "youtube"
    assert detect_platform("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "youtube"
    assert detect_platform("https://youtube.com/@channel") == "web"  # not a video
    assert detect_platform("https://www.reddit.com/r/python/comments/abc/t/") == "reddit"
    assert detect_platform("https://github.com/psf/requests") == "github"
    assert detect_platform("https://github.com/features/actions") == "web"  # reserved, not a repo
    assert detect_platform("https://blog.example.com/feed") == "feed"
    assert detect_platform("https://example.com/atom.xml") == "feed"
    assert detect_platform("https://example.com/article") == "web"


# --- reader_get redirect SSRF guard ---


class _FakeResp:
    def __init__(self, status, headers=None, text="ok"):
        self.status_code = status
        self.headers = headers or {}
        self.text = text


def _fake_session(responses):
    """A fake curl_cffi AsyncSession yielding the queued responses in order."""
    calls = iter(responses)

    class _S:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **k):
            return next(calls)

    return lambda *a, **k: _S()


async def test_reader_get_revalidates_redirect_target():
    from pawgrab.utils.url_safety import SSRFError

    redirect = _FakeResp(302, {"location": "http://169.254.169.254/latest/meta-data/"})
    with patch("pawgrab.engine.reader_http.AsyncSession", _fake_session([redirect])):
        from pawgrab.engine.reader_http import reader_get

        with pytest.raises(SSRFError):
            await reader_get("https://feed.example.com/rss")


async def test_reader_get_follows_public_redirect():
    hop = _FakeResp(302, {"location": "https://cdn.example.com/final"})
    final = _FakeResp(200, text="body")
    with patch("pawgrab.engine.reader_http.AsyncSession", _fake_session([hop, final])):
        from pawgrab.engine.reader_http import reader_get

        resp = await reader_get("https://example.com/start")
    assert resp.status_code == 200
    assert resp.text == "body"


# --- reddit ---


def test_reddit_detection_and_json_url():
    assert is_reddit("https://old.reddit.com/r/x/") is True
    assert is_reddit("https://example.com") is False
    assert _json_url("https://www.reddit.com/r/python/comments/abc/title/?x=1") == "https://www.reddit.com/r/python/comments/abc/title.json?x=1"
    assert _json_url("https://reddit.com/r/python").endswith("/r/python.json")


def test_reddit_comments_flatten_nested_and_skip_non_t1():
    listing = {
        "data": {
            "children": [
                {
                    "kind": "t1",
                    "data": {
                        "author": "a",
                        "body": "hi",
                        "score": 3,
                        "replies": {"data": {"children": [{"kind": "t1", "data": {"author": "b", "body": "re", "score": 1, "replies": ""}}]}},
                    },
                },
                {"kind": "more", "data": {}},
            ]
        }
    }
    out = _comments(listing)
    assert len(out) == 1
    assert out[0]["replies"][0]["author"] == "b"


# --- github ---


def test_github_parse_repo():
    assert parse_repo("https://github.com/psf/requests") == ("psf", "requests")
    assert parse_repo("https://github.com/psf/requests.git/tree/main") == ("psf", "requests")
    assert parse_repo("https://github.com/settings/profile") is None  # reserved owner
    assert parse_repo("https://github.com/") is None
    assert parse_repo("https://example.com/a/b") is None


# --- transcript helpers ---


def test_extract_video_id():
    assert extract_video_id("https://www.youtube.com/watch?v=abc123DEF_X&t=10") == "abc123DEF_X"
    assert extract_video_id("https://youtu.be/abc123DEF_X") == "abc123DEF_X"
    assert extract_video_id("https://www.youtube.com/shorts/abc123DEF_X") == "abc123DEF_X"
    assert extract_video_id("https://example.com/x") is None


def test_extract_json_object_balances_braces():
    text = 'var ytInitialPlayerResponse = {"a":{"b":"}"},"c":1}; more junk'
    assert _extract_json_object(text, "ytInitialPlayerResponse") == '{"a":{"b":"}"},"c":1}'
    assert _extract_json_object("nothing here", "ytInitialPlayerResponse") is None


def test_pick_track_prefers_manual_then_language():
    tracks = [
        {"languageCode": "en", "kind": "asr", "baseUrl": "a"},
        {"languageCode": "es", "baseUrl": "b"},
    ]
    assert _pick_track(tracks, None)["baseUrl"] == "b"  # manual beats asr
    assert _pick_track(tracks, ["en"])["baseUrl"] == "a"  # requested language wins
    assert _pick_track([], None) is None


def test_parse_timedtext():
    xml = '<transcript><text start="0" dur="1.5">hi &amp; bye</text><text start="1.5" dur="2">  </text><text start="3.5" dur="1">next</text></transcript>'
    segs = _parse_timedtext(xml)
    assert len(segs) == 2  # blank entry dropped
    assert segs[0] == {"start": 0.0, "duration": 1.5, "text": "hi & bye"}


# --- feed parsing ---


def test_parse_rss():
    rss = (
        "<rss><channel><title>T</title><link>http://x</link><description>D</description>"
        "<item><title>I1</title><link>http://x/1</link><pubDate>Mon</pubDate><description>hi</description><guid>g1</guid></item></channel></rss>"
    )
    feed = _parse_rss(safe_fromstring(rss), 10)
    assert feed["type"] == "rss"
    assert feed["title"] == "T"
    assert feed["items"][0]["link"] == "http://x/1"


def test_parse_atom_link_and_author():
    atom = (
        '<feed xmlns="http://www.w3.org/2005/Atom"><title>AT</title><link href="http://a"/>'
        '<entry><title>E1</title><link href="http://a/1" rel="alternate"/><updated>2026</updated>'
        "<summary>s</summary><id>id1</id><author><name>me</name></author></entry></feed>"
    )
    feed = _parse_atom(safe_fromstring(atom), 10)
    assert feed["type"] == "atom"
    assert feed["items"][0]["link"] == "http://a/1"
    assert feed["items"][0]["author"] == "me"


# --- API endpoints ---


async def test_capabilities_endpoint(client):
    resp = await client.get("/health/capabilities")
    assert resp.status_code == 200
    body = resp.json()
    assert "capabilities" in body and "fetch" in body["capabilities"]


async def test_transcript_endpoint_success(client):
    fake = {
        "video_id": "abc123DEF_X",
        "title": "Demo",
        "language": "en",
        "auto_generated": False,
        "segments": [{"start": 0.0, "duration": 1.0, "text": "hello"}],
        "text": "hello",
    }
    with patch("pawgrab.api.reader.fetch_transcript", new_callable=AsyncMock, return_value=fake):
        resp = await client.post("/v1/transcript", json={"url": "https://youtu.be/abc123DEF_X"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["text"] == "hello"


async def test_transcript_endpoint_soft_fails_without_captions(client):
    with patch("pawgrab.api.reader.fetch_transcript", new_callable=AsyncMock, side_effect=ValueError("no captions available for this video")):
        resp = await client.post("/v1/transcript", json={"url": "https://youtu.be/abc123DEF_X"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "no captions" in data["error"]


async def test_feed_endpoint_success(client):
    fake = {"type": "rss", "title": "T", "link": "http://x", "description": "D", "items": [{"title": "I1", "link": "http://x/1"}], "count": 1}
    with patch("pawgrab.api.reader.fetch_feed", new_callable=AsyncMock, return_value=fake):
        resp = await client.post("/v1/feed", json={"url": "https://x/feed"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["count"] == 1


async def test_read_routes_youtube_to_transcript(client):
    fake = {"video_id": "abc123DEF_X", "title": "D", "language": "en", "auto_generated": False, "segments": [{"start": 0.0, "duration": 1.0, "text": "hi"}], "text": "hi"}
    with patch("pawgrab.api.reader.fetch_transcript", new_callable=AsyncMock, return_value=fake):
        resp = await client.post("/v1/read", json={"url": "https://youtu.be/abc123DEF_X"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["kind"] == "youtube"
    assert data["transcript"]["text"] == "hi"
    assert data["feed"] is None


async def test_read_routes_feed(client):
    fake = {"type": "atom", "title": "T", "link": "http://x", "description": None, "items": [], "count": 0}
    with patch("pawgrab.api.reader.fetch_feed", new_callable=AsyncMock, return_value=fake):
        resp = await client.post("/v1/read", json={"url": "https://x/atom.xml"})
    assert resp.status_code == 200
    assert resp.json()["kind"] == "feed"


async def test_reddit_endpoint_success(client):
    fake = {"kind": "post", "post": {"title": "Hello", "author": "u"}, "comments": [{"author": "c", "body": "hi", "replies": []}]}
    with patch("pawgrab.api.reader.fetch_reddit", new_callable=AsyncMock, return_value=fake):
        resp = await client.post("/v1/reddit", json={"url": "https://www.reddit.com/r/python/comments/abc/t/"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["post"]["title"] == "Hello"
    assert data["comments"][0]["body"] == "hi"


async def test_github_endpoint_success(client):
    fake = {"full_name": "psf/requests", "stars": 52000, "language": "Python", "topics": ["http"]}
    with patch("pawgrab.api.reader.fetch_repo", new_callable=AsyncMock, return_value=fake):
        resp = await client.post("/v1/github", json={"url": "https://github.com/psf/requests"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["full_name"] == "psf/requests"
    assert data["stars"] == 52000


async def test_github_endpoint_soft_fails_on_non_repo(client):
    with patch("pawgrab.api.reader.fetch_repo", new_callable=AsyncMock, side_effect=ValueError("not a GitHub repository URL")):
        resp = await client.post("/v1/github", json={"url": "https://github.com/"})
    assert resp.status_code == 200
    assert resp.json()["success"] is False


async def test_read_routes_reddit(client):
    fake = {"kind": "listing", "posts": [{"title": "P1"}]}
    with patch("pawgrab.api.reader.fetch_reddit", new_callable=AsyncMock, return_value=fake):
        resp = await client.post("/v1/read", json={"url": "https://www.reddit.com/r/python/"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["kind"] == "reddit"
    assert data["reddit"]["posts"][0]["title"] == "P1"


async def test_read_routes_github(client):
    fake = {"full_name": "psf/requests", "stars": 1}
    with patch("pawgrab.api.reader.fetch_repo", new_callable=AsyncMock, return_value=fake):
        resp = await client.post("/v1/read", json={"url": "https://github.com/psf/requests"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["kind"] == "github"
    assert data["github"]["full_name"] == "psf/requests"
