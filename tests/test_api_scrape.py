"""Tests for the /v1/scrape endpoint."""

from pawgrab import __version__


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    # API itself must always be "ok"; overall status may be "unhealthy" when
    # Redis is unavailable, or "degraded" when browser pool is down (expected
    # in test environments without Redis/browser).
    assert data["status"] in ("ok", "degraded", "unhealthy")
    assert data["checks"]["api"] == "ok"


async def test_status(client):
    resp = await client.get("/status")
    data = resp.json()
    assert data["service"] == "pawgrab"
    assert data["version"] == __version__


async def test_scrape_missing_url(client):
    resp = await client.post("/v1/scrape", json={})
    assert resp.status_code == 422


async def test_scrape_invalid_url(client):
    resp = await client.post("/v1/scrape", json={"url": "not-a-url"})
    assert resp.status_code == 422
