from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _make_app():
    from pawgrab.middleware.idempotency import IdempotencyMiddleware

    app = FastAPI()
    app.add_middleware(IdempotencyMiddleware)

    @app.post("/v1/crawl")
    async def crawl():
        return {"job_id": "newjob12345", "status": "queued"}

    @app.post("/v1/other")
    async def other():
        return {"result": "not idempotent"}

    return app


class _FakeRedis:
    """Minimal Redis emulation honoring SET NX semantics for idempotency tests."""

    def __init__(self, initial=None):
        self.store = dict(initial or {})

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key):
        self.store.pop(key, None)


async def test_non_idempotent_path_passes_through():
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/v1/other", headers={"Idempotency-Key": "key1"})
    assert resp.status_code == 200
    assert resp.json()["result"] == "not idempotent"


async def test_no_idempotency_key_passes_through():
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/v1/crawl")
    assert resp.status_code == 200
    assert resp.json()["job_id"] == "newjob12345"


async def test_redis_unavailable_passes_through():
    app = _make_app()
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, side_effect=Exception("no redis")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/crawl", headers={"Idempotency-Key": "key1"})
    assert resp.status_code == 200


async def test_cache_miss_processes_request():
    app = _make_app()
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock()
    mock_redis.delete = AsyncMock()
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=mock_redis):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/crawl", headers={"Idempotency-Key": "my-idem-key"})
    assert resp.status_code == 200
    assert resp.json()["job_id"] == "newjob12345"


def _key(idem: str, auth: str) -> str:
    import hashlib

    client_id = hashlib.sha256(auth.encode()).hexdigest()[:16]
    return f"pawgrab:idempotency:/v1/crawl:{client_id}:{idem}"


async def test_cache_hit_replays_cached_response():
    import orjson

    app = _make_app()
    auth = "Bearer tok"
    done = orjson.dumps({"state": "done", "status_code": 200, "body": {"job_id": "cached123", "status": "queued"}}).decode()
    fake = _FakeRedis({_key("replay-key", auth): done})
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=fake):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/crawl", headers={"Idempotency-Key": "replay-key", "Authorization": auth})
    assert resp.status_code == 200
    assert resp.json()["job_id"] == "cached123"
    assert resp.headers.get("x-idempotency-replay") == "true"


async def test_idempotency_key_scoped_to_client():
    app = _make_app()
    fake = _FakeRedis()
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=fake):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r1 = await client.post("/v1/crawl", headers={"Idempotency-Key": "same-key", "Authorization": "Bearer token_a"})
            r2 = await client.post("/v1/crawl", headers={"Idempotency-Key": "same-key", "Authorization": "Bearer token_b"})

    assert r1.status_code == 200
    assert r2.status_code == 200


async def test_same_key_different_body_conflicts():
    """A reused key with a different payload must be rejected, not mis-replayed."""
    app = _make_app()

    @app.post("/v1/crawl")
    async def crawl():
        return {"job_id": "x"}

    fake = _FakeRedis()
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=fake):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r1 = await client.post("/v1/crawl", headers={"Idempotency-Key": "k"}, json={"url": "a"})
            r2 = await client.post("/v1/crawl", headers={"Idempotency-Key": "k"}, json={"url": "b"})
    assert r1.status_code == 200
    assert r2.status_code == 422


async def test_in_flight_request_conflicts():
    """A second request while the first is still in progress gets 409."""
    import hashlib

    import orjson

    app = _make_app()
    auth = "Bearer tok"

    empty_hash = hashlib.sha256(b"").hexdigest()[:16]
    fake = _FakeRedis({_key("busy", auth): orjson.dumps({"state": "in_progress", "body_hash": empty_hash}).decode()})
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=fake):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/crawl", headers={"Idempotency-Key": "busy", "Authorization": auth})
    assert resp.status_code == 409
