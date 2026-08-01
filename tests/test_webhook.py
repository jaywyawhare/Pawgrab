"""Tests for webhook delivery."""

from unittest.mock import AsyncMock, MagicMock, patch

from pawgrab.engine.webhook import send_webhook


async def test_webhook_success():
    """Successful webhook POST returns True."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("pawgrab.engine.webhook.AsyncSession") as mock_session:
        session_instance = AsyncMock()
        session_instance.post = AsyncMock(return_value=mock_resp)
        mock_session.return_value.__aenter__ = AsyncMock(return_value=session_instance)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await send_webhook(
            "https://webhook.example.com/hook",
            job_id="abc123def456",
            job_type="crawl",
            status="completed",
            pages_scraped=10,
        )

    import orjson

    assert result is True
    session_instance.post.assert_called_once()
    call_kwargs = session_instance.post.call_args
    payload = orjson.loads(call_kwargs.kwargs["data"])
    assert payload["job_id"] == "abc123def456"
    assert payload["job_type"] == "crawl"
    assert payload["status"] == "completed"
    assert payload["pages_scraped"] == 10


async def test_webhook_failure_returns_false():
    """Network error on webhook returns False, doesn't raise."""
    with patch("pawgrab.engine.webhook.AsyncSession") as mock_session:
        session_instance = AsyncMock()
        session_instance.post = AsyncMock(side_effect=ConnectionError("refused"))
        mock_session.return_value.__aenter__ = AsyncMock(return_value=session_instance)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await send_webhook(
            "https://webhook.example.com/hook",
            job_id="abc123",
            job_type="crawl",
            status="failed",
            error="timeout",
        )

    assert result is False


async def test_webhook_non_2xx_returns_false():
    """Non-2xx response from webhook returns False."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500

    with patch("pawgrab.engine.webhook.AsyncSession") as mock_session:
        session_instance = AsyncMock()
        session_instance.post = AsyncMock(return_value=mock_resp)
        mock_session.return_value.__aenter__ = AsyncMock(return_value=session_instance)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await send_webhook(
            "https://webhook.example.com/hook",
            job_id="abc123",
            job_type="batch",
            status="completed",
        )

    assert result is False


async def test_webhook_payload_shape():
    """Verify all expected fields are in the webhook payload."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    captured_payload = {}

    async def capture_post(url, **kwargs):
        import orjson

        captured_payload.update(orjson.loads(kwargs["data"]))
        return mock_resp

    with patch("pawgrab.engine.webhook.AsyncSession") as mock_session:
        session_instance = AsyncMock()
        session_instance.post = capture_post
        mock_session.return_value.__aenter__ = AsyncMock(return_value=session_instance)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        await send_webhook(
            "https://hook.test",
            job_id="j1",
            job_type="crawl",
            status="completed",
            pages_scraped=5,
            total_pages=10,
            error=None,
        )

    assert set(captured_payload.keys()) == {
        "job_id",
        "job_type",
        "status",
        "pages_scraped",
        "total_pages",
        "error",
    }


async def test_webhook_hmac_signature(monkeypatch):
    """When a signing secret is set, deliveries carry a verifiable signature."""
    import hashlib
    import hmac

    from pawgrab.config import settings

    monkeypatch.setattr(settings, "webhook_secret", "s3cr3t")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    captured = {}

    async def capture_post(url, **kwargs):
        captured["data"] = kwargs["data"]
        captured["headers"] = kwargs["headers"]
        return mock_resp

    with patch("pawgrab.engine.webhook.AsyncSession") as mock_session:
        session_instance = AsyncMock()
        session_instance.post = capture_post
        mock_session.return_value.__aenter__ = AsyncMock(return_value=session_instance)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
        await send_webhook("https://hook.test", job_id="j", job_type="crawl", status="completed")

    sig = captured["headers"]["X-Pawgrab-Signature"]
    expected = "sha256=" + hmac.new(b"s3cr3t", captured["data"], hashlib.sha256).hexdigest()
    assert sig == expected


async def test_webhook_blocks_ssrf():
    """A webhook pointed at a private IP is refused without sending."""
    result = await send_webhook("http://169.254.169.254/", job_id="j", job_type="crawl", status="completed")
    assert result is False
