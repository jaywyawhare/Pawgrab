"""Tests for job lifecycle: list, cancel, dead-letter queue."""

from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from pawgrab.main import app


class _FakeRedis:
    def __init__(self):
        self.hashes = {}
        self.zsets = {}
        self.lists = {}

    async def hgetall(self, key):
        return self.hashes.get(key, {})

    async def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    async def hset(self, key, mapping=None, **kw):
        self.hashes.setdefault(key, {}).update(mapping or kw)

    async def expire(self, *a, **k):
        return True

    async def exists(self, key):
        return 1 if key in self.hashes else 0

    async def zadd(self, key, mapping):
        self.zsets.setdefault(key, {}).update(mapping)

    async def zcard(self, key):
        return len(self.zsets.get(key, {}))

    async def zrevrange(self, key, start, stop):
        items = sorted(self.zsets.get(key, {}).items(), key=lambda x: x[1], reverse=True)
        return [k for k, _ in items[start : stop + 1]]

    async def zrem(self, key, member):
        self.zsets.get(key, {}).pop(member, None)

    async def lpush(self, key, val):
        self.lists.setdefault(key, []).insert(0, val)

    async def ltrim(self, *a, **k):
        return True

    async def lrange(self, key, start, stop):
        return self.lists.get(key, [])[start : stop + 1]


async def test_cancel_crawl_flags_job():
    from pawgrab.queue.manager import cancel_crawl_job, crawl_cancel_requested

    fake = _FakeRedis()
    fake.hashes["pawgrab:crawl:abc123def456"] = {"status": "in_progress"}
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=fake):
        assert await cancel_crawl_job("abc123def456") is True
        assert await crawl_cancel_requested("abc123def456") is True


async def test_cancel_missing_job_returns_false():
    from pawgrab.queue.manager import cancel_crawl_job

    fake = _FakeRedis()
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=fake):
        assert await cancel_crawl_job("aaaaaaaaaaaa") is False


async def test_cancel_completed_job_returns_false():
    from pawgrab.queue.manager import cancel_crawl_job

    fake = _FakeRedis()
    fake.hashes["pawgrab:crawl:dddddddddddd"] = {"status": "completed"}
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=fake):
        assert await cancel_crawl_job("dddddddddddd") is False


async def test_list_crawl_jobs():
    from pawgrab.queue.manager import list_crawl_jobs

    fake = _FakeRedis()
    fake.zsets["pawgrab:crawl:index"] = {"1111aaaaaaaa": 100, "2222bbbbbbbb": 200}
    fake.hashes["pawgrab:crawl:1111aaaaaaaa"] = {"status": "completed", "created_at": "100"}
    fake.hashes["pawgrab:crawl:2222bbbbbbbb"] = {"status": "in_progress", "created_at": "200"}
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=fake):
        jobs, total = await list_crawl_jobs()
    assert total == 2
    assert jobs[0]["job_id"] == "2222bbbbbbbb"


async def test_dead_letter_roundtrip():
    from pawgrab.queue.manager import get_dead_letters, record_dead_letter

    fake = _FakeRedis()
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=fake):
        await record_dead_letter("crawl", "faaaaaaaaa11", "boom", meta={"url": "https://x"})
        entries = await get_dead_letters()
    assert len(entries) == 1
    assert entries[0]["job_id"] == "faaaaaaaaa11"
    assert entries[0]["error"] == "boom"


async def test_cancel_endpoint():
    fake = _FakeRedis()
    fake.hashes["pawgrab:crawl:eeee11112222"] = {"status": "in_progress"}
    with patch("pawgrab.queue.manager.get_redis", new_callable=AsyncMock, return_value=fake):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/v1/crawl/eeee11112222")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelling"
