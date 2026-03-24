"""Tests for screenshot and PDF capture functionality."""

from unittest.mock import AsyncMock, MagicMock, patch

from pawgrab.engine.fetcher import _fetch_with_browser


async def test_screenshot_capture():
    """Verify screenshot bytes are captured from Playwright page."""
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    page = AsyncMock()
    page.url = "https://example.com"
    page.content = AsyncMock(return_value="<html><body>Hello</body></html>")
    page.screenshot = AsyncMock(return_value=fake_png)
    page.pdf = AsyncMock()
    page.context = MagicMock()

    response = MagicMock()
    response.status = 200
    response.headers = {}
    page.goto = AsyncMock(return_value=response)

    pool = AsyncMock()
    pool.acquire = AsyncMock(return_value=page)
    pool.release = AsyncMock()

    with patch("pawgrab.engine.fetcher.detect_challenge") as mock_detect:
        mock_detect.return_value = MagicMock(detected=False)
        result = await _fetch_with_browser(
            "https://example.com",
            pool=pool,
            capture_screenshot=True,
            screenshot_fullpage=True,
        )

    assert result.screenshot_bytes == fake_png
    page.screenshot.assert_called_once_with(full_page=True)
    assert result.pdf_bytes is None


async def test_pdf_capture():
    """Verify PDF bytes are captured from Playwright page."""
    fake_pdf = b"%PDF-1.4" + b"\x00" * 100
    page = AsyncMock()
    page.url = "https://example.com"
    page.content = AsyncMock(return_value="<html><body>Hello</body></html>")
    page.screenshot = AsyncMock()
    page.pdf = AsyncMock(return_value=fake_pdf)
    page.context = MagicMock()

    response = MagicMock()
    response.status = 200
    response.headers = {}
    page.goto = AsyncMock(return_value=response)

    pool = AsyncMock()
    pool.acquire = AsyncMock(return_value=page)
    pool.release = AsyncMock()

    with patch("pawgrab.engine.fetcher.detect_challenge") as mock_detect:
        mock_detect.return_value = MagicMock(detected=False)
        result = await _fetch_with_browser(
            "https://example.com",
            pool=pool,
            capture_pdf=True,
        )

    assert result.pdf_bytes == fake_pdf
    page.pdf.assert_called_once()
    assert result.screenshot_bytes is None


async def test_screenshot_failure_graceful():
    """Screenshot failure should not crash — returns None."""
    page = AsyncMock()
    page.url = "https://example.com"
    page.content = AsyncMock(return_value="<html></html>")
    page.screenshot = AsyncMock(side_effect=Exception("GPU error"))
    page.context = MagicMock()

    response = MagicMock()
    response.status = 200
    response.headers = {}
    page.goto = AsyncMock(return_value=response)

    pool = AsyncMock()
    pool.acquire = AsyncMock(return_value=page)
    pool.release = AsyncMock()

    with patch("pawgrab.engine.fetcher.detect_challenge") as mock_detect:
        mock_detect.return_value = MagicMock(detected=False)
        result = await _fetch_with_browser(
            "https://example.com",
            pool=pool,
            capture_screenshot=True,
        )

    assert result.screenshot_bytes is None
    assert result.html == "<html></html>"


async def test_scrape_request_screenshot_fields():
    """ScrapeRequest model accepts screenshot/pdf fields."""
    from pawgrab.models.scrape import ScrapeRequest

    req = ScrapeRequest(
        url="https://example.com",
        screenshot=True,
        screenshot_fullpage=False,
        pdf=True,
    )
    assert req.screenshot is True
    assert req.screenshot_fullpage is False
    assert req.pdf is True


async def test_scrape_response_base64_fields():
    """ScrapeResponse model accepts base64 fields."""
    from pawgrab.models.scrape import ScrapeResponse

    resp = ScrapeResponse(
        success=True,
        url="https://example.com",
        screenshot_base64="aGVsbG8=",
        pdf_base64="d29ybGQ=",
    )
    assert resp.screenshot_base64 == "aGVsbG8="
    assert resp.pdf_base64 == "d29ybGQ="


async def test_browser_unavailable_returns_503(client):
    """Screenshot request without browser pool should return 503."""
    with patch("pawgrab.dependencies.get_browser_pool", side_effect=Exception("no browser")):
        resp = await client.post(
            "/v1/scrape",
            json={
                "url": "https://example.com",
                "screenshot": True,
            },
        )
    assert resp.status_code == 503
    data = resp.json()
    assert "Browser pool" in data["error"]
    assert data["code"] == "browser_unavailable"
