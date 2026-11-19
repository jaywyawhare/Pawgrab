"""Tests for the content index (F4)."""

from unittest.mock import AsyncMock, patch

import pytest

from pawgrab.engine import index as index_engine


@pytest.fixture(autouse=True)
def _memory_store(monkeypatch):
    """Force the in-memory fallback (no Redis) and clear it per test."""
    index_engine._local.clear()
    monkeypatch.setattr(index_engine, "_redis", AsyncMock(return_value=None))
    yield
    index_engine._local.clear()


async def test_upsert_and_search():
    await index_engine.upsert("https://a.com/pricing", "Pricing plans: pro is $20 per month", "Pricing")
    await index_engine.upsert("https://a.com/blog", "A blog post about cats and dogs", "Blog")
    hits = await index_engine.search("pricing per month", k=5)
    assert hits
    assert hits[0]["url"] == "https://a.com/pricing"
    assert hits[0]["score"] > 0


async def test_upsert_skips_unchanged():
    assert await index_engine.upsert("https://a.com/x", "same content here") is True
    assert await index_engine.upsert("https://a.com/x", "same content here") is False  # unchanged
    assert await index_engine.upsert("https://a.com/x", "new content now") is True  # changed


async def test_stats_counts_entries():
    await index_engine.upsert("https://a.com/1", "one two three")
    await index_engine.upsert("https://a.com/2", "four five six")
    stats = await index_engine.stats()
    assert stats["entries"] == 2
    assert stats["store"] == "memory"


async def test_delete_domain():
    await index_engine.upsert("https://a.com/1", "alpha content")
    await index_engine.upsert("https://b.com/1", "beta content")
    removed = await index_engine.delete_domain("a.com")
    assert removed == 1
    stats = await index_engine.stats()
    assert stats["entries"] == 1


async def test_disabled_index_skips(monkeypatch):
    monkeypatch.setattr(index_engine.settings, "index_enabled", False)
    assert await index_engine.upsert("https://a.com/x", "content") is False


async def test_index_search_endpoint(client):
    await index_engine.upsert("https://a.com/docs", "documentation for the api reference", "Docs")
    with patch("pawgrab.engine.index._redis", new_callable=AsyncMock, return_value=None):
        resp = await client.post("/index/search", json={"query": "api documentation", "k": 3})
    data = resp.json()
    assert resp.status_code == 200
    assert data["total"] >= 1
    assert data["hits"][0]["url"] == "https://a.com/docs"


async def test_index_stats_endpoint(client):
    resp = await client.get("/index/stats")
    assert resp.status_code == 200
    assert "entries" in resp.json()
