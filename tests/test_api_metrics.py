from unittest.mock import AsyncMock, patch


async def test_prometheus_metrics(client):
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "pawgrab_scrape_total" in resp.text
    assert "# TYPE" in resp.text
    assert "# HELP" in resp.text


async def test_json_metrics(client):
    resp = await client.get("/v1/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "scrape" in data
    assert "extract" in data
    assert "crawl" in data
    assert "browser_sessions" in data
    scrape = data["scrape"]
    assert "total" in scrape
    assert "success" in scrape
    assert "failed" in scrape
    assert "cached" in scrape


async def test_browser_pool_metrics_unavailable(client):
    with patch("pawgrab.dependencies.try_browser_pool", new_callable=AsyncMock, return_value=None):
        resp = await client.get("/v1/metrics/browser-pool")
    assert resp.status_code == 200
    assert resp.json()["status"] == "unavailable"


async def test_usage_summary(client):
    resp = await client.get("/v1/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_requests" in data
    assert "unique_clients" in data


async def test_client_usage(client):
    from pawgrab.engine.analytics import usage_tracker

    usage_tracker.record_request("anonymous", "/v1/scrape", response_size=512)
    resp = await client.get("/v1/usage/anonymous")
    assert resp.status_code == 200
    data = resp.json()
    assert data["client"] == "anonymous"
    assert data["total_requests"] >= 1


async def test_client_usage_other_key_forbidden(client):
    """A caller cannot read another client's usage analytics."""
    resp = await client.get("/v1/usage/some_other_client")
    assert resp.status_code == 403


async def test_unknown_client_usage(client):

    resp = await client.get("/v1/usage/nonexistent_client_xyz")
    assert resp.status_code == 403
