"""Tests for the vendored-in meta-search engine (native SERP scraping + merge)."""

from unittest.mock import AsyncMock, MagicMock, patch

from pawgrab.engine.search_provider import (
    SearchResult,
    _bing_real_url,
    _ddg_real_url,
    _engine_bing,
    _engine_duckduckgo,
    _merge,
    _normalize_url,
    search_structured,
    search_web,
)


def _session_returning(html: str):
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.get = AsyncMock(return_value=MagicMock(status_code=200, text=html))
    return session


# --- redirect decoding --------------------------------------------------------


def test_ddg_real_url_decodes_redirect():
    href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Freal.example%2Fpage&rut=abc"
    assert _ddg_real_url(href) == "https://real.example/page"


def test_ddg_real_url_direct_and_invalid():
    assert _ddg_real_url("https://direct.example/x") == "https://direct.example/x"
    assert _ddg_real_url("javascript:void(0)") is None
    assert _ddg_real_url("") is None


def test_bing_real_url_direct():
    assert _bing_real_url("https://real.example/p") == "https://real.example/p"


def test_bing_real_url_decodes_ck_redirect():
    import base64

    target = "https://decoded.example/page"
    token = "a1" + base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
    href = f"https://www.bing.com/ck/a?u={token}&p=1"
    assert _bing_real_url(href) == target


# --- URL normalization / merge (SearXNG scoring) ------------------------------


def test_normalize_url_strips_www_and_trailing_slash():
    assert _normalize_url("https://www.Example.com/path/") == _normalize_url("https://example.com/path")


def test_merge_dedupes_and_scores_cross_engine_agreement_higher():
    # 'shared' is #1 on both engines; 'solo' only on ddg at #2.
    engine_results = {
        "duckduckgo": [("https://shared.example/", "Shared", "s"), ("https://solo.example/", "Solo", "s")],
        "bing": [("https://shared.example", "Shared bing", "longer snippet here")],
    }
    merged = _merge(engine_results)
    assert merged[0].url.startswith("https://shared.example")
    # Shared appears in both engines -> higher score than the single-engine result.
    assert merged[0].score > merged[1].score
    top = merged[0]
    assert top.engines == {"duckduckgo", "bing"}
    # Merge kept the longer snippet.
    assert top.content == "longer snippet here"


def test_merge_prefers_https():
    r = _merge({"a": [("http://x.example/p", "t", "c")], "b": [("https://x.example/p", "t", "c")]})
    assert r[0].url == "https://x.example/p"


# --- engine scraping ----------------------------------------------------------


async def test_engine_duckduckgo_scrapes():
    html = """
    <div class="result web-result">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fone.example%2F">One</a>
      <a class="result__snippet">first snippet</a>
    </div>
    <div class="result web-result">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Ftwo.example%2F">Two</a>
    </div>
    """
    with patch("pawgrab.engine.search_provider.AsyncSession", return_value=_session_returning(html)):
        out = await _engine_duckduckgo("test", 5)
    assert [u for u, _, _ in out] == ["https://one.example/", "https://two.example/"]
    assert out[0][2] == "first snippet"


async def test_engine_bing_scrapes():
    html = """
    <ol id="b_results">
      <li class="b_algo"><h2><a href="https://first.example/">First</a></h2><p>desc</p></li>
      <li class="b_algo"><h2><a href="https://second.example/">Second</a></h2></li>
    </ol>
    """
    with patch("pawgrab.engine.search_provider.AsyncSession", return_value=_session_returning(html)):
        out = await _engine_bing("test", 5)
    assert [u for u, _, _ in out] == ["https://first.example/", "https://second.example/"]


async def test_engine_duckduckgo_bad_status_returns_empty():
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.get = AsyncMock(return_value=MagicMock(status_code=429, text=""))
    with patch("pawgrab.engine.search_provider.AsyncSession", return_value=session):
        assert await _engine_duckduckgo("test", 5) == []


# --- public API + dispatch ----------------------------------------------------


async def test_search_web_returns_urls():
    with patch("pawgrab.engine.search_provider.settings") as s:
        s.search_provider = "duckduckgo"
        s.google_search_api_key = ""
        with patch(
            "pawgrab.engine.search_provider._engine_duckduckgo",
            new_callable=AsyncMock,
            return_value=[("https://a.com", "A", ""), ("https://b.com", "B", "")],
        ):
            assert await search_web("q") == ["https://a.com", "https://b.com"]


async def test_search_structured_shape_and_ranking():
    with patch("pawgrab.engine.search_provider.settings") as s:
        s.search_provider = "auto"
        s.google_search_api_key = ""
        with (
            patch(
                "pawgrab.engine.search_provider._engine_duckduckgo",
                new_callable=AsyncMock,
                return_value=[("https://shared.com", "Shared", "x")],
            ),
            patch(
                "pawgrab.engine.search_provider._engine_bing",
                new_callable=AsyncMock,
                return_value=[("https://shared.com", "Shared", "x")],
            ),
        ):
            results = await search_structured("q", 5)
    assert results[0]["link"] == "https://shared.com"
    assert set(results[0]["engines"]) == {"duckduckgo", "bing"}
    assert results[0]["position"] == 1
    assert "score" in results[0]


async def test_search_engine_failure_is_isolated():
    with patch("pawgrab.engine.search_provider.settings") as s:
        s.search_provider = "auto"
        s.google_search_api_key = ""
        with (
            patch("pawgrab.engine.search_provider._engine_duckduckgo", new_callable=AsyncMock, side_effect=Exception("down")),
            patch(
                "pawgrab.engine.search_provider._engine_bing",
                new_callable=AsyncMock,
                return_value=[("https://ok.com", "OK", "")],
            ),
        ):
            results = await search_web("q")
    assert results == ["https://ok.com"]


async def test_google_without_key_falls_back_to_meta():
    from pawgrab.engine.search_provider import _select_engines

    with patch("pawgrab.engine.search_provider.settings") as s:
        s.google_search_api_key = ""
        assert _select_engines("google") == ["duckduckgo", "bing"]


def test_search_result_dataclass_defaults():
    r = SearchResult(url="https://x.com")
    assert r.engines == set() and r.positions == [] and r.score == 0.0
