from unittest.mock import AsyncMock, patch


async def test_crawl_missing_url(client):
    resp = await client.post("/v1/crawl", json={})
    assert resp.status_code == 422


async def test_crawl_invalid_url(client):
    resp = await client.post("/v1/crawl", json={"url": "not-a-url"})
    assert resp.status_code == 422


async def test_crawl_creates_job(client):
    with (
        patch("pawgrab.api.crawl.create_job", new_callable=AsyncMock, return_value="abcdef123456"),
        patch("pawgrab.api.crawl.get_arq_pool", new_callable=AsyncMock) as mock_pool,
    ):
        pool = AsyncMock()
        pool.enqueue_job = AsyncMock()
        mock_pool.return_value = pool
        resp = await client.post("/v1/crawl", json={"url": "https://example.com"})

    assert resp.status_code == 202
    data = resp.json()
    assert data["job_id"] == "abcdef123456"
    assert data["status"] == "queued"
    assert "example.com" in data["url"]


async def test_crawl_with_options(client):
    with (
        patch("pawgrab.api.crawl.create_job", new_callable=AsyncMock, return_value="abc123def456"),
        patch("pawgrab.api.crawl.get_arq_pool", new_callable=AsyncMock) as mock_pool,
    ):
        pool = AsyncMock()
        pool.enqueue_job = AsyncMock()
        mock_pool.return_value = pool
        resp = await client.post(
            "/v1/crawl",
            json={"url": "https://example.com", "max_pages": 50, "max_depth": 5, "strategy": "dfs"},
        )

    assert resp.status_code == 202


async def test_crawl_queue_unavailable(client):
    with (
        patch("pawgrab.api.crawl.create_job", new_callable=AsyncMock, return_value="abcdef123456"),
        patch("pawgrab.api.crawl.get_arq_pool", new_callable=AsyncMock, side_effect=Exception("Redis down")),
    ):
        resp = await client.post("/v1/crawl", json={"url": "https://example.com"})

    assert resp.status_code == 503
    assert resp.json()["code"] == "queue_unavailable"


async def test_crawl_status_invalid_job_id(client):
    resp = await client.get("/v1/crawl/not-valid!")
    assert resp.status_code == 400


async def test_crawl_status_not_found(client):
    with patch("pawgrab.api.crawl.get_job", new_callable=AsyncMock, return_value=None):
        resp = await client.get("/v1/crawl/abcdef123456")

    assert resp.status_code == 404
    assert resp.json()["code"] == "resource_not_found"


async def test_crawl_status_found(client):
    from pawgrab.models.crawl import CrawlResponse, CrawlStatus

    job = CrawlResponse(
        job_id="abcdef123456",
        status=CrawlStatus.IN_PROGRESS,
        url="https://example.com",
        pages_scraped=5,
    )
    with patch("pawgrab.api.crawl.get_job", new_callable=AsyncMock, return_value=job):
        resp = await client.get("/v1/crawl/abcdef123456")

    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == "abcdef123456"
    assert data["status"] == "in_progress"


async def test_crawl_with_domain_filters(client):
    with (
        patch("pawgrab.api.crawl.create_job", new_callable=AsyncMock, return_value="abc123456789"),
        patch("pawgrab.api.crawl.get_arq_pool", new_callable=AsyncMock) as mock_pool,
    ):
        pool = AsyncMock()
        pool.enqueue_job = AsyncMock()
        mock_pool.return_value = pool
        resp = await client.post(
            "/v1/crawl",
            json={
                "url": "https://example.com",
                "allowed_domains": ["example.com"],
                "blocked_domains": ["ads.example.com"],
            },
        )

    assert resp.status_code == 202
