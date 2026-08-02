from unittest.mock import AsyncMock, patch


async def test_create_schedule_missing_url(client):
    assert (await client.post("/v1/schedule", json={})).status_code == 422


async def test_create_schedule_missing_cron(client):
    assert (await client.post("/v1/schedule", json={"url": "https://example.com"})).status_code == 422


def _schedule_data(schedule_id="abc123def456", **overrides):
    data = {
        "schedule_id": schedule_id,
        "url": "https://example.com",
        "cron": "0 * * * *",
        "max_pages": 10,
        "max_depth": 3,
        "formats": ["markdown"],
        "webhook_url": None,
        "strategy": "bfs",
        "created_at": 1700000000,
        "last_run": 0,
        "next_run": 1700003600,
        "run_count": 0,
        "enabled": True,
    }
    data.update(overrides)
    return data


async def test_create_schedule_success(client):
    with (
        patch("pawgrab.api.schedule.create_schedule", new_callable=AsyncMock, return_value="abc123def456"),
        patch("pawgrab.api.schedule.get_schedule", new_callable=AsyncMock, return_value=_schedule_data()),
    ):
        resp = await client.post("/v1/schedule", json={"url": "https://example.com", "cron": "0 * * * *"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["schedule_id"] == "abc123def456"
    assert data["url"] == "https://example.com"
    assert data["cron"] == "0 * * * *"


async def test_create_schedule_redis_unavailable(client):
    with patch("pawgrab.api.schedule.create_schedule", new_callable=AsyncMock, side_effect=Exception("Redis down")):
        resp = await client.post("/v1/schedule", json={"url": "https://example.com", "cron": "0 * * * *"})

    assert resp.status_code == 503
    assert resp.json()["code"] == "queue_unavailable"


async def test_list_schedules_empty(client):
    with patch("pawgrab.api.schedule.list_schedules", new_callable=AsyncMock, return_value=[]):
        resp = await client.get("/v1/schedules")

    data = resp.json()
    assert data["schedules"] == []
    assert data["total"] == 0


async def test_list_schedules(client):
    schedules = [_schedule_data(schedule_id=f"sid{i}", url=f"https://example{i}.com") for i in range(3)]
    with patch("pawgrab.api.schedule.list_schedules", new_callable=AsyncMock, return_value=schedules):
        resp = await client.get("/v1/schedules")

    data = resp.json()
    assert data["total"] == 3
    assert len(data["schedules"]) == 3


async def test_get_schedule_not_found(client):
    with patch("pawgrab.api.schedule.get_schedule", new_callable=AsyncMock, return_value=None):
        resp = await client.get("/v1/schedule/abc123def456")

    assert resp.status_code == 404
    assert resp.json()["code"] == "resource_not_found"


async def test_get_schedule_found(client):
    with patch("pawgrab.api.schedule.get_schedule", new_callable=AsyncMock, return_value=_schedule_data(run_count=2, cron="*/5 * * * *")):
        resp = await client.get("/v1/schedule/abc123def456")

    assert resp.status_code == 200
    data = resp.json()
    assert data["schedule_id"] == "abc123def456"
    assert data["run_count"] == 2


async def test_delete_schedule_not_found(client):
    with patch("pawgrab.api.schedule.delete_schedule", new_callable=AsyncMock, return_value=False):
        resp = await client.delete("/v1/schedule/abc123def456")

    assert resp.status_code == 404
    assert resp.json()["code"] == "resource_not_found"


async def test_delete_schedule_success(client):
    with patch("pawgrab.api.schedule.delete_schedule", new_callable=AsyncMock, return_value=True):
        resp = await client.delete("/v1/schedule/abc123def456")

    assert resp.status_code == 200
    assert resp.json()["success"] is True
