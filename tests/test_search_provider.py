from unittest.mock import AsyncMock, MagicMock, patch

from pawgrab.engine.search_provider import (
    _search_duckduckgo,
    _search_google,
    _search_serpapi,
    search_web,
)


async def test_search_web_duckduckgo_default():
    with patch("pawgrab.engine.search_provider.settings") as mock_settings:
        mock_settings.search_provider = "duckduckgo"
        mock_settings.serpapi_key = ""
        mock_settings.google_search_api_key = ""
        with patch("pawgrab.engine.search_provider._search_duckduckgo", new_callable=AsyncMock, return_value=["https://a.com"]) as mock_ddg:
            result = await search_web("python tutorial")
    mock_ddg.assert_called_once_with("python tutorial", 5)
    assert result == ["https://a.com"]


async def test_search_web_serpapi():
    with patch("pawgrab.engine.search_provider.settings") as mock_settings:
        mock_settings.search_provider = "serpapi"
        mock_settings.serpapi_key = "mykey"
        mock_settings.google_search_api_key = ""
        with patch("pawgrab.engine.search_provider._search_serpapi", new_callable=AsyncMock, return_value=["https://b.com"]) as mock_serp:
            result = await search_web("test query", num_results=3)
    mock_serp.assert_called_once_with("test query", 3)
    assert result == ["https://b.com"]


async def test_search_web_google():
    with patch("pawgrab.engine.search_provider.settings") as mock_settings:
        mock_settings.search_provider = "google"
        mock_settings.serpapi_key = ""
        mock_settings.google_search_api_key = "gkey"
        with patch("pawgrab.engine.search_provider._search_google", new_callable=AsyncMock, return_value=["https://c.com"]) as mock_google:
            result = await search_web("test")
    mock_google.assert_called_once()
    assert result == ["https://c.com"]


async def test_search_web_falls_back_to_ddg_when_serpapi_key_missing():
    with patch("pawgrab.engine.search_provider.settings") as mock_settings:
        mock_settings.search_provider = "serpapi"
        mock_settings.serpapi_key = ""
        mock_settings.google_search_api_key = ""
        with patch("pawgrab.engine.search_provider._search_duckduckgo", new_callable=AsyncMock, return_value=[]) as mock_ddg:
            await search_web("test")
    mock_ddg.assert_called_once()


async def test_search_duckduckgo_success():
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)
    mock_ddgs.text.return_value = [
        {"href": "https://example.com/1"},
        {"href": "https://example.com/2"},
    ]
    with patch("duckduckgo_search.DDGS", return_value=mock_ddgs):
        result = await _search_duckduckgo("python", 5)
    assert result == ["https://example.com/1", "https://example.com/2"]


async def test_search_duckduckgo_skips_empty_href():
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)
    mock_ddgs.text.return_value = [
        {"href": "https://example.com/1"},
        {"href": ""},
        {"title": "no href"},
    ]
    with patch("duckduckgo_search.DDGS", return_value=mock_ddgs):
        assert await _search_duckduckgo("python", 5) == ["https://example.com/1"]


async def test_search_duckduckgo_exception_returns_empty():
    with patch("duckduckgo_search.DDGS", side_effect=ImportError("not installed")):
        assert await _search_duckduckgo("test", 5) == []


async def test_search_serpapi_success():
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.get = AsyncMock(
        return_value=MagicMock(
            json=lambda: {
                "organic_results": [
                    {"link": "https://serpapi-result.com/1"},
                    {"link": "https://serpapi-result.com/2"},
                ]
            }
        )
    )

    with patch("pawgrab.engine.search_provider.settings") as mock_settings:
        mock_settings.serpapi_key = "test_key"
        with patch("pawgrab.engine.search_provider.AsyncSession", return_value=mock_session):
            result = await _search_serpapi("test", 5)

    assert result == ["https://serpapi-result.com/1", "https://serpapi-result.com/2"]


async def test_search_serpapi_exception_returns_empty():
    with patch("pawgrab.engine.search_provider.AsyncSession", side_effect=Exception("network error")):
        assert await _search_serpapi("test", 5) == []


async def test_search_google_success():
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.get = AsyncMock(
        return_value=MagicMock(
            json=lambda: {
                "items": [
                    {"link": "https://google-result.com/1"},
                    {"link": "https://google-result.com/2"},
                ]
            }
        )
    )

    with patch("pawgrab.engine.search_provider.settings") as mock_settings:
        mock_settings.google_search_api_key = "gkey"
        mock_settings.google_search_cx = "cx"
        with patch("pawgrab.engine.search_provider.AsyncSession", return_value=mock_session):
            result = await _search_google("test", 5)

    assert result == ["https://google-result.com/1", "https://google-result.com/2"]


async def test_search_google_exception_returns_empty():
    with patch("pawgrab.engine.search_provider.AsyncSession", side_effect=Exception("timeout")):
        assert await _search_google("test", 5) == []


async def test_search_web_searxng():
    with patch("pawgrab.engine.search_provider.settings") as mock_settings:
        mock_settings.search_provider = "searxng"
        mock_settings.serpapi_key = ""
        mock_settings.google_search_api_key = ""
        mock_settings.searxng_base_url = "https://searx.example"
        with patch(
            "pawgrab.engine.search_provider._search_searxng",
            new_callable=AsyncMock,
            return_value=["https://sx.com"],
        ) as mock_sx:
            from pawgrab.engine.search_provider import search_web

            assert await search_web("q") == ["https://sx.com"]
            mock_sx.assert_awaited_once()


async def test_search_searxng_success():
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.get = AsyncMock(
        return_value=MagicMock(
            status_code=200,
            json=lambda: {
                "results": [
                    {"url": "https://a.com"},
                    {"url": "https://b.com"},
                    {"url": "https://a.com"},  # duplicate -> deduped
                ]
            },
        )
    )
    with patch("pawgrab.engine.search_provider.settings") as mock_settings:
        mock_settings.searxng_base_url = "https://searx.example/"
        mock_settings.searxng_engines = ""
        with patch("pawgrab.engine.search_provider.AsyncSession", return_value=mock_session):
            from pawgrab.engine.search_provider import _search_searxng

            result = await _search_searxng("test", 5)
    assert result == ["https://a.com", "https://b.com"]


async def test_search_searxng_bad_status_returns_empty():
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.get = AsyncMock(return_value=MagicMock(status_code=403, json=lambda: {}))
    with patch("pawgrab.engine.search_provider.settings") as mock_settings:
        mock_settings.searxng_base_url = "https://searx.example"
        mock_settings.searxng_engines = ""
        with patch("pawgrab.engine.search_provider.AsyncSession", return_value=mock_session):
            from pawgrab.engine.search_provider import _search_searxng

            assert await _search_searxng("test", 5) == []


async def test_search_serpapi_error_field_returns_empty():
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.get = AsyncMock(return_value=MagicMock(json=lambda: {"error": "Invalid API key"}))
    with patch("pawgrab.engine.search_provider.settings") as mock_settings:
        mock_settings.serpapi_key = "bad"
        with patch("pawgrab.engine.search_provider.AsyncSession", return_value=mock_session):
            assert await _search_serpapi("test", 5) == []
