import time
from unittest.mock import AsyncMock, patch


async def test_create_session(client):
    with (
        patch("pawgrab.api.session.create_session", new_callable=AsyncMock, return_value="abc1234567890123"),
        patch("pawgrab.api.session.update_session", new_callable=AsyncMock),
    ):
        resp = await client.post("/v1/session", json={})

    assert resp.status_code == 200
    assert resp.json()["session_id"] == "abc1234567890123"


async def test_create_session_with_cookies(client):
    with (
        patch("pawgrab.api.session.create_session", new_callable=AsyncMock, return_value="sid123456789012"),
        patch("pawgrab.api.session.update_session", new_callable=AsyncMock) as mock_update,
    ):
        resp = await client.post("/v1/session", json={"cookies": {"token": "abc123"}})

    assert resp.status_code == 200
    mock_update.assert_called_once()
    assert mock_update.call_args.kwargs.get("cookies") == {"token": "abc123"}


async def test_create_session_redis_unavailable(client):
    with patch("pawgrab.api.session.create_session", new_callable=AsyncMock, side_effect=Exception("Redis down")):
        resp = await client.post("/v1/session", json={})

    assert resp.status_code == 503
    assert resp.json()["code"] == "queue_unavailable"


async def test_get_session_not_found(client):
    with patch("pawgrab.api.session.get_session", new_callable=AsyncMock, return_value=None):
        resp = await client.get("/v1/session/nonexistentsid1")

    assert resp.status_code == 404
    assert resp.json()["code"] == "resource_not_found"


async def test_get_session_found(client):
    now = int(time.time())
    session_data = {
        "session_id": "mysession123456",
        "cookies": {"auth": "token123"},
        "local_storage": {},
        "headers": {},
        "created_at": now,
        "last_used": now,
    }
    with patch("pawgrab.api.session.get_session", new_callable=AsyncMock, return_value=session_data):
        resp = await client.get("/v1/session/mysession123456")

    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "mysession123456"
    assert data["cookies"] == {"auth": "token123"}


async def test_update_session_not_found(client):
    with patch("pawgrab.api.session.update_session", new_callable=AsyncMock, return_value=False):
        resp = await client.put("/v1/session/nonexistent00000", json={"cookies": {"x": "y"}})

    assert resp.status_code == 404
    assert resp.json()["code"] == "resource_not_found"


async def test_update_session_success(client):
    now = int(time.time())
    updated = {
        "session_id": "mysession123456",
        "cookies": {"new_cookie": "value"},
        "local_storage": {},
        "headers": {},
        "created_at": now,
        "last_used": now,
    }
    with (
        patch("pawgrab.api.session.update_session", new_callable=AsyncMock, return_value=True),
        patch("pawgrab.api.session.get_session", new_callable=AsyncMock, return_value=updated),
    ):
        resp = await client.put("/v1/session/mysession123456", json={"cookies": {"new_cookie": "value"}})

    assert resp.status_code == 200
    assert resp.json()["cookies"] == {"new_cookie": "value"}


async def test_delete_session_not_found(client):
    with patch("pawgrab.api.session.delete_session", new_callable=AsyncMock, return_value=False):
        resp = await client.delete("/v1/session/nonexistent00000")
    assert resp.status_code == 404


async def test_delete_session_success(client):
    with patch("pawgrab.api.session.delete_session", new_callable=AsyncMock, return_value=True):
        resp = await client.delete("/v1/session/mysession123456")

    assert resp.status_code == 200
    assert resp.json()["success"] is True
