"""Tests for Phase 6: Media and link extraction."""

from pawgrab.engine.media import extract_all_media

SAMPLE_HTML = """
<html><body>
<img src="/img/photo.jpg" alt="A photo" width="800" height="600">
<img data-src="/img/lazy.png" alt="Lazy loaded">
<video poster="/poster.jpg">
    <source src="/video.mp4" type="video/mp4">
</video>
<audio>
    <source src="/audio.mp3" type="audio/mpeg">
</audio>
<iframe src="https://www.youtube.com/embed/abc123" width="560" height="315"></iframe>
<a href="/about" title="About us">About</a>
<a href="https://external.com">External</a>
<a href="mailto:test@example.com">Email</a>
<a href="#section">Anchor</a>
<div style="background: url('/bg.png')"></div>
</body></html>
"""


class TestMediaExtraction:
    def test_extracts_images(self):
        result = extract_all_media(SAMPLE_HTML, "https://example.com")
        images = result["images"]
        assert len(images) >= 2
        # Regular img
        srcs = [img["src"] for img in images]
        assert "https://example.com/img/photo.jpg" in srcs

    def test_extracts_lazy_loaded_images(self):
        result = extract_all_media(SAMPLE_HTML, "https://example.com")
        images = result["images"]
        srcs = [img["src"] for img in images]
        assert "https://example.com/img/lazy.png" in srcs

    def test_extracts_background_images(self):
        result = extract_all_media(SAMPLE_HTML, "https://example.com")
        images = result["images"]
        bg_images = [img for img in images if img.get("source") == "css-background"]
        assert len(bg_images) >= 1

    def test_extracts_videos(self):
        result = extract_all_media(SAMPLE_HTML, "https://example.com")
        videos = result["videos"]
        assert len(videos) >= 1
        # HTML5 video
        assert any("/video.mp4" in str(v) for v in videos)

    def test_extracts_embedded_videos(self):
        result = extract_all_media(SAMPLE_HTML, "https://example.com")
        videos = result["videos"]
        embeds = [v for v in videos if v.get("embed")]
        assert len(embeds) >= 1

    def test_extracts_audio(self):
        result = extract_all_media(SAMPLE_HTML, "https://example.com")
        audio = result["audio"]
        assert len(audio) >= 1

    def test_extracts_links(self):
        result = extract_all_media(SAMPLE_HTML, "https://example.com")
        links = result["links"]
        hrefs = [link["href"] for link in links]
        assert "https://example.com/about" in hrefs
        assert "https://external.com" in hrefs

    def test_skips_mailto_and_anchor_links(self):
        result = extract_all_media(SAMPLE_HTML, "https://example.com")
        links = result["links"]
        hrefs = [link["href"] for link in links]
        assert not any("mailto:" in h for h in hrefs)
        assert not any(h == "#section" for h in hrefs)

    def test_image_metadata(self):
        result = extract_all_media(SAMPLE_HTML, "https://example.com")
        photo = next(i for i in result["images"] if "photo" in i["src"])
        assert photo["alt"] == "A photo"
        assert photo["width"] == "800"
        assert photo["height"] == "600"
