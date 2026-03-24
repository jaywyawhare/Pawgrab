"""Tests for the /v1/batch/scrape endpoint."""

from unittest.mock import AsyncMock, patch


async def test_batch_scrape_missing_urls(client):
    resp = await client.post("/v1/batch/scrape", json={})
    assert resp.status_code == 422


async def test_batch_scrape_empty_urls(client):
    resp = await client.post("/v1/batch/scrape", json={"urls": []})
    assert resp.status_code == 422


async def test_batch_scrape_too_many_urls(client):
    urls = [f"https://example.com/{i}" for i in range(101)]
    resp = await client.post("/v1/batch/scrape", json={"urls": urls})
    assert resp.status_code == 422


async def test_batch_scrape_invalid_url(client):
    resp = await client.post("/v1/batch/scrape", json={"urls": ["not-a-url"]})
    assert resp.status_code == 422


async def test_batch_scrape_creation(client):
    """Batch scrape should return 202 with job_id."""
    with (
        patch("pawgrab.api.batch.create_batch_job", new_callable=AsyncMock) as mock_create,
        patch("pawgrab.api.batch.get_arq_pool", new_callable=AsyncMock) as mock_pool,
    ):
        mock_create.return_value = "abcdef123456"
        pool = AsyncMock()
        pool.enqueue_job = AsyncMock()
        mock_pool.return_value = pool

        resp = await client.post("/v1/batch/scrape", json={
            "urls": ["https://example.com", "https://example.org"],
        })

    assert resp.status_code == 202
    data = resp.json()
    assert data["job_id"] == "abcdef123456"
    assert data["status"] == "queued"
    assert data["total_urls"] == 2


async def test_batch_status_invalid_job_id(client):
    resp = await client.get("/v1/batch/invalid!")
    assert resp.status_code == 400


async def test_batch_status_not_found(client):
    with patch("pawgrab.api.batch.get_batch_job", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        resp = await client.get("/v1/batch/abcdef123456")
    assert resp.status_code == 404


async def test_batch_status_found(client):
    with patch("pawgrab.api.batch.get_batch_job", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {
            "job_id": "abcdef123456",
            "status": "completed",
            "urls_scraped": 2,
            "total_urls": 2,
            "results": [],
            "error": None,
        }
        resp = await client.get("/v1/batch/abcdef123456")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["urls_scraped"] == 2


async def test_batch_queue_unavailable(client):
    """Should return 503 when queue is down."""
    with (
        patch("pawgrab.api.batch.create_batch_job", new_callable=AsyncMock) as mock_create,
        patch("pawgrab.api.batch.get_arq_pool", new_callable=AsyncMock) as mock_pool,
    ):
        mock_create.return_value = "abcdef123456"
        mock_pool.side_effect = Exception("Redis down")

        resp = await client.post("/v1/batch/scrape", json={
            "urls": ["https://example.com"],
        })

    assert resp.status_code == 503
