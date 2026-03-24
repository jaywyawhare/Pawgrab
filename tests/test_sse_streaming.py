"""Tests for SSE streaming crawl progress."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from pawgrab.models.crawl import CrawlJobStatus, CrawlStatus
from pawgrab.queue.manager import _pubsub_channel, publish_event


class TestPubSubChannel:
    def test_channel_name(self):
        assert _pubsub_channel("abc123def456") == "pawgrab:events:abc123def456"


class TestPublishEvent:
    async def test_publish_event_sends_json(self):
        with patch("pawgrab.queue.manager.get_redis") as mock_get:
            mock_redis = AsyncMock()
            mock_get.return_value = mock_redis

            await publish_event("job123", "page_scraped", {"url": "https://example.com", "pages_scraped": 1, "max_pages": 10})

            mock_redis.publish.assert_awaited_once()
            channel, payload = mock_redis.publish.call_args[0]
            assert channel == "pawgrab:events:job123"
            data = json.loads(payload)
            assert data["type"] == "page_scraped"
            assert data["url"] == "https://example.com"


class TestSSEEndpoint:
    """Test the SSE endpoint via the FastAPI router."""

    @pytest.fixture
    def app(self):
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse

        from pawgrab.api.crawl import router
        from pawgrab.exceptions import PawgrabError

        app = FastAPI()
        app.include_router(router, prefix="/v1")

        @app.exception_handler(PawgrabError)
        async def pawgrab_error_handler(request: Request, exc: PawgrabError):
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": exc.message, "code": exc.code.value},
            )

        return app

    async def test_404_for_missing_job(self, app):
        import httpx

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            with patch("pawgrab.api.crawl.get_job", return_value=None):
                resp = await client.get("/v1/crawl/abc123def456/stream")
                assert resp.status_code == 404

    async def test_completed_job_returns_final_event(self, app):
        import httpx

        job = CrawlJobStatus(
            job_id="abc123def456",
            status=CrawlStatus.COMPLETED,
            pages_scraped=5,
            results=[],
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            with patch("pawgrab.api.crawl.get_job", return_value=job):
                resp = await client.get("/v1/crawl/abc123def456/stream")
                assert resp.status_code == 200
                assert "text/event-stream" in resp.headers["content-type"]
                assert "event: completed" in resp.text
                assert "pages_scraped" in resp.text

    async def test_content_type_is_event_stream(self, app):
        import httpx

        job = CrawlJobStatus(
            job_id="abc123def456",
            status=CrawlStatus.COMPLETED,
            pages_scraped=0,
            results=[],
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            with patch("pawgrab.api.crawl.get_job", return_value=job):
                resp = await client.get("/v1/crawl/abc123def456/stream")
                assert "text/event-stream" in resp.headers["content-type"]

    async def test_invalid_job_id(self, app):
        import httpx

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/crawl/invalid!/stream")
            assert resp.status_code == 400

    async def test_failed_job_includes_error(self, app):
        import httpx

        job = CrawlJobStatus(
            job_id="abc123def456",
            status=CrawlStatus.FAILED,
            pages_scraped=3,
            results=[],
            error="Connection timeout",
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            with patch("pawgrab.api.crawl.get_job", return_value=job):
                resp = await client.get("/v1/crawl/abc123def456/stream")
                assert "event: failed" in resp.text
                assert "Connection timeout" in resp.text
