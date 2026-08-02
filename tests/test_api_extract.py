from unittest.mock import AsyncMock, patch


async def test_extract_missing_url(client):
    assert (await client.post("/v1/extract", json={})).status_code == 422


async def test_extract_invalid_url(client):
    assert (await client.post("/v1/extract", json={"url": "not-a-url"})).status_code == 422


async def test_extract_css_strategy(client):
    from pawgrab.engine.fetcher import FetchResult

    mock_result = FetchResult(
        html='<html><body><h1 class="title">Hello</h1></body></html>',
        status_code=200,
        url="https://example.com",
    )
    with (
        patch("pawgrab.api.extract.guard_url", new_callable=AsyncMock),
        patch("pawgrab.api.extract.fetch_page", new_callable=AsyncMock, return_value=mock_result),
        patch("pawgrab.api.extract.try_browser_pool", new_callable=AsyncMock, return_value=None),
    ):
        resp = await client.post(
            "/v1/extract",
            json={"url": "https://example.com", "strategy": "css", "selectors": {"title": "h1.title"}},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "example.com" in data["url"]


async def test_extract_table_strategy(client):
    from pawgrab.engine.fetcher import FetchResult

    html = """<html><body>
<table>
  <thead><tr><th>Name</th><th>Score</th></tr></thead>
  <tbody><tr><td>Alice</td><td>95</td></tr></tbody>
</table>
</body></html>"""
    with (
        patch("pawgrab.api.extract.guard_url", new_callable=AsyncMock),
        patch("pawgrab.api.extract.fetch_page", new_callable=AsyncMock, return_value=FetchResult(html=html, status_code=200, url="https://example.com")),
        patch("pawgrab.api.extract.try_browser_pool", new_callable=AsyncMock, return_value=None),
    ):
        resp = await client.post("/v1/extract", json={"url": "https://example.com", "strategy": "table"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert isinstance(data["data"], list)


async def test_extract_llm_no_prompt(client):
    with patch("pawgrab.api.extract.try_browser_pool", new_callable=AsyncMock, return_value=None):
        resp = await client.post("/v1/extract", json={"url": "https://example.com", "strategy": "llm"})

    assert resp.status_code == 400
    assert resp.json()["code"] == "validation_error"


async def test_extract_llm_no_provider(client):
    with (
        patch("pawgrab.api.extract.try_browser_pool", new_callable=AsyncMock, return_value=None),
        patch("pawgrab.api.extract.settings") as mock_settings,
    ):
        mock_settings.llm_provider = "openai"
        mock_settings.openai_api_key = ""
        resp = await client.post(
            "/v1/extract",
            json={"url": "https://example.com", "strategy": "llm", "prompt": "Extract all headings"},
        )

    assert resp.status_code == 503
    assert resp.json()["code"] == "llm_unavailable"


async def test_extract_robots_blocked(client):
    with (
        patch("pawgrab.api.extract.guard_url", new_callable=AsyncMock, side_effect=PermissionError("blocked")),
        patch("pawgrab.api.extract.try_browser_pool", new_callable=AsyncMock, return_value=None),
    ):
        resp = await client.post(
            "/v1/extract",
            json={"url": "https://example.com", "strategy": "css", "selectors": {"title": "h1"}},
        )

    assert resp.status_code == 403
    assert resp.json()["code"] == "robots_blocked"


async def test_extract_fetch_timeout(client):
    with (
        patch("pawgrab.api.extract.guard_url", new_callable=AsyncMock),
        patch("pawgrab.api.extract.fetch_page", new_callable=AsyncMock, side_effect=TimeoutError("timed out")),
        patch("pawgrab.api.extract.try_browser_pool", new_callable=AsyncMock, return_value=None),
    ):
        resp = await client.post(
            "/v1/extract",
            json={"url": "https://example.com", "strategy": "css", "selectors": {"t": "h1"}},
        )

    assert resp.status_code == 504
    assert resp.json()["code"] == "timeout"


async def test_extract_fetch_error(client):
    with (
        patch("pawgrab.api.extract.guard_url", new_callable=AsyncMock),
        patch("pawgrab.api.extract.fetch_page", new_callable=AsyncMock, side_effect=ConnectionError("failed")),
        patch("pawgrab.api.extract.try_browser_pool", new_callable=AsyncMock, return_value=None),
    ):
        resp = await client.post(
            "/v1/extract",
            json={"url": "https://example.com", "strategy": "css", "selectors": {"t": "h1"}},
        )

    assert resp.status_code == 502
