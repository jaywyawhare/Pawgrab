from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pawgrab.middleware.rate_limit import APIRateLimitMiddleware


def _make_app(rpm: int = 600) -> FastAPI:
    app = FastAPI()
    app.add_middleware(APIRateLimitMiddleware, rpm=rpm)

    @app.get("/test")
    def handler():
        return {"ok": True}

    return app


class TestClientKeyExtraction:
    def test_bearer_token_used_as_key(self):
        middleware = APIRateLimitMiddleware(_make_app(), rpm=600)
        req = MagicMock()
        req.headers = {"Authorization": "Bearer mytoken123"}
        req.client = MagicMock(host="1.2.3.4")
        assert middleware._get_client_key(req) == "key:mytoken123"

    def test_ip_used_when_no_auth(self):
        middleware = APIRateLimitMiddleware(_make_app(), rpm=600)
        req = MagicMock()
        req.headers = {}
        req.client = MagicMock(host="1.2.3.4")
        with patch("pawgrab.config.settings") as mock_settings:
            mock_settings.trusted_proxy_ips = ""
            assert middleware._get_client_key(req) == "ip:1.2.3.4"

    def test_unknown_ip_when_no_client(self):
        middleware = APIRateLimitMiddleware(_make_app(), rpm=600)
        req = MagicMock()
        req.headers = {}
        req.client = None
        with patch("pawgrab.config.settings") as mock_settings:
            mock_settings.trusted_proxy_ips = ""
            assert middleware._get_client_key(req) == "ip:unknown"

    def test_trusted_proxy_uses_forwarded_for(self):
        middleware = APIRateLimitMiddleware(_make_app(), rpm=600)
        req = MagicMock()
        req.headers = {"X-Forwarded-For": "10.0.0.1, 10.0.0.2"}
        req.client = MagicMock(host="192.168.1.1")
        with patch("pawgrab.config.settings") as mock_settings:
            mock_settings.trusted_proxy_ips = "192.168.1.1"
            assert middleware._get_client_key(req) == "ip:10.0.0.1"

    def test_untrusted_proxy_ignores_forwarded_for(self):
        middleware = APIRateLimitMiddleware(_make_app(), rpm=600)
        req = MagicMock()
        req.headers = {"X-Forwarded-For": "10.0.0.1"}
        req.client = MagicMock(host="1.2.3.4")
        with patch("pawgrab.config.settings") as mock_settings:
            mock_settings.trusted_proxy_ips = "192.168.1.1"
            assert middleware._get_client_key(req) == "ip:1.2.3.4"


class TestSkipPaths:
    @pytest.mark.parametrize("path", ["/health", "/docs"])
    def test_not_rate_limited(self, path):
        client = TestClient(_make_app(rpm=1))
        assert client.get(path).status_code != 429
        assert client.get(path).status_code != 429


class TestRateLimitHeaders:
    def test_response_includes_headers(self):
        resp = TestClient(_make_app(rpm=100)).get("/test")
        assert resp.status_code == 200
        assert resp.headers.get("x-ratelimit-limit") == "100"
        assert "x-ratelimit-remaining" in resp.headers


@pytest.mark.asyncio
async def test_rate_limit_exceeded_returns_429():
    from starlette.requests import Request

    app = _make_app(rpm=1)
    middleware = APIRateLimitMiddleware(app, rpm=1)

    mock_limiter = MagicMock()
    mock_limiter.has_capacity.return_value = False
    mock_limiter.max_rate = 1

    async def _mock_get_limiter(key):
        return mock_limiter

    middleware._get_limiter = _mock_get_limiter

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/v1/scrape",
        "query_string": b"",
        "headers": [],
        "app": app,
    }
    request = Request(scope)
    request.state.request_id = "test-id"

    response = await middleware.dispatch(request, AsyncMock())
    assert response.status_code == 429
    assert response.headers.get("Retry-After") == "60"
