from unittest.mock import AsyncMock, patch

from pawgrab import __version__


async def test_health_api_always_ok(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["checks"]["api"] == "ok"
    assert data["version"] == __version__
    assert data["status"] in ("ok", "degraded", "unhealthy")
    assert "memory" in data["checks"]


async def test_health_redis_unavailable(client):
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, side_effect=Exception("no redis")):
        resp = await client.get("/health")

    data = resp.json()
    assert data["checks"]["redis"] == "unavailable"
    assert data["status"] == "unhealthy"


async def test_health_redis_ok_browser_unavailable(client):
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    with (
        patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=mock_redis),
        patch("pawgrab.dependencies.get_browser_pool", new_callable=AsyncMock, side_effect=Exception("no browser")),
    ):
        resp = await client.get("/health")

    data = resp.json()
    assert data["checks"]["redis"] == "ok"
    assert data["checks"]["browser_pool"] == "unavailable"
    assert data["status"] == "degraded"


async def test_status_endpoint(client):
    resp = await client.get("/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["service"] == "pawgrab"
    assert data["version"] == __version__
    assert data["status"] == "ok"
