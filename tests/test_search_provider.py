"""Tests for the vendored-in meta-search engine (native SERP scraping + merge)."""

from unittest.mock import AsyncMock, MagicMock, patch

from pawgrab.engine.search_provider import (
    EngineResult,
    SearchParams,
    SearchResult,
    _bing_real_url,
    _ddg_real_url,
    _engine_bing,
    _engine_duckduckgo,
    _engine_mojeek,
    _engine_yahoo,
    _fetch_instant_answers,
    _merge,
    _normalize_url,
    _r,
    _region_to_market,
    _select_engines,
    _yahoo_real_url,
    search,
    search_structured,
    search_web,
)


def _session_returning(html: str):
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.get = AsyncMock(return_value=MagicMock(status_code=200, text=html))
    return session


def _json_session(payload):
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.get = AsyncMock(return_value=MagicMock(status_code=200, json=lambda: payload))
    return session


# --- redirect decoding --------------------------------------------------------


def test_ddg_real_url_decodes_redirect():
    href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Freal.example%2Fpage&rut=abc"
    assert _ddg_real_url(href) == "https://real.example/page"


def test_bing_real_url_decodes_ck_redirect():
    import base64

    target = "https://decoded.example/page"
    token = "a1" + base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
    assert _bing_real_url(f"https://www.bing.com/ck/a?u={token}") == target


def test_yahoo_real_url_decodes_ru():
    href = "https://r.search.yahoo.com/_ylt=.../RU=https%3A%2F%2Ftarget.example%2Fp/RK=2/RS=abc"
    assert _yahoo_real_url(href) == "https://target.example/p"
    assert _yahoo_real_url("https://direct.example/x") == "https://direct.example/x"


def test_region_to_market():
    assert _region_to_market("us-en") == "en-US"


# --- URL normalization / merge (SearXNG scoring) ------------------------------


def test_normalize_url_strips_www_and_trailing_slash():
    assert _normalize_url("https://www.Example.com/path/") == _normalize_url("https://example.com/path")


def test_merge_dedupes_and_scores_cross_engine_agreement_higher():
    engine_results = {
        "duckduckgo": [_r("https://shared.example/", "Shared", "s"), _r("https://solo.example/", "Solo", "s")],
        "bing": [_r("https://shared.example", "Shared bing", "longer snippet here")],
    }
    merged = _merge(engine_results)
    assert merged[0].url.startswith("https://shared.example")
    assert merged[0].score > merged[1].score
    assert merged[0].engines == {"duckduckgo", "bing"}
    assert merged[0].content == "longer snippet here"


def test_merge_prefers_https_and_keeps_thumbnail():
    r = _merge(
        {
            "a": [_r("http://x.example/p", "t", "c")],
            "b": [_r("https://x.example/p", "t", "c", "images", thumbnail="https://t.png")],
        }
    )
    assert r[0].url == "https://x.example/p"
    assert r[0].thumbnail == "https://t.png"


# --- query params -------------------------------------------------------------


def test_search_params_normalized_clamps():
    p = SearchParams(page=0, time_range="bogus", safesearch=9, category="zzz").normalized()
    assert p.page == 1 and p.time_range is None and p.safesearch == 0 and p.category == "general"


async def test_ddg_applies_page_time_and_safesearch_params():
    session = _session_returning("<html></html>")
    with patch("pawgrab.engine.search_provider.AsyncSession", return_value=session):
        await _engine_duckduckgo("q", 5, SearchParams(page=2, time_range="week", safesearch=2, region="uk-en"))
    sent = session.get.await_args.kwargs["params"]
    assert sent["kl"] == "uk-en" and sent["df"] == "w" and sent["kp"] == "1" and sent["s"] > 0


async def test_bing_applies_pagination_and_market():
    session = _session_returning("<html></html>")
    with patch("pawgrab.engine.search_provider.AsyncSession", return_value=session):
        await _engine_bing("q", 5, SearchParams(page=3, safesearch=1, region="us-en"))
    sent = session.get.await_args.kwargs["params"]
    assert sent["mkt"] == "en-US" and sent["adlt"] == "moderate" and sent["first"] > 1


# --- engine scraping ----------------------------------------------------------


async def test_engine_duckduckgo_scrapes():
    html = """
    <div class="result web-result">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fone.example%2F">One</a>
      <a class="result__snippet">first snippet</a>
    </div>
    """
    with patch("pawgrab.engine.search_provider.AsyncSession", return_value=_session_returning(html)):
        out = await _engine_duckduckgo("test", 5, SearchParams())
    assert out.results[0]["url"] == "https://one.example/"
    assert out.results[0]["content"] == "first snippet"


async def test_engine_bing_general_with_suggestions_and_corrections():
    html = """
    <ol id="b_results"><li class="b_algo"><h2><a href="https://first.example/">First</a></h2><p>d</p></li></ol>
    <div id="b_rs"><a href="/s?q=more">more</a></div>
    <div id="sp_requery"><a href="/s?q=fixed">did you mean fixed</a></div>
    """
    with patch("pawgrab.engine.search_provider.AsyncSession", return_value=_session_returning(html)):
        out = await _engine_bing("test", 5, SearchParams())
    assert out.results[0]["url"] == "https://first.example/"
    assert "more" in out.suggestions
    assert "did you mean fixed" in out.corrections


async def test_engine_bing_news_category():
    html = '<div class="newsitem"><a class="title" href="https://news.example/a">Headline</a><div class="snippet">blurb</div></div>'
    with patch("pawgrab.engine.search_provider.AsyncSession", return_value=_session_returning(html)):
        out = await _engine_bing("test", 5, SearchParams(category="news"))
    assert out.results[0]["type"] == "news"
    assert out.results[0]["url"] == "https://news.example/a"


async def test_engine_bing_images_category():
    import orjson

    m = orjson.dumps({"murl": "https://img.example/a.jpg", "turl": "https://t.example/a.jpg", "t": "cat"}).decode()
    html = f"<a class=\"iusc\" m='{m}'></a>"
    with patch("pawgrab.engine.search_provider.AsyncSession", return_value=_session_returning(html)):
        out = await _engine_bing("cats", 5, SearchParams(category="images"))
    assert out.results[0]["url"] == "https://img.example/a.jpg"
    assert out.results[0]["thumbnail"] == "https://t.example/a.jpg"
    assert out.results[0]["type"] == "images"


async def test_engine_mojeek_scrapes():
    html = '<ul class="results-standard"><li><h2><a href="https://moj.example/">M</a></h2><p class="s">snip</p></li></ul>'
    with patch("pawgrab.engine.search_provider.AsyncSession", return_value=_session_returning(html)):
        out = await _engine_mojeek("test", 5, SearchParams())
    assert out.results[0]["url"] == "https://moj.example/"


async def test_engine_yahoo_scrapes_and_decodes():
    html = '<div class="algo"><h3><a href="https://r.search.yahoo.com/_x/RU=https%3A%2F%2Fy.example%2Fp/RK=2/">Y</a></h3><p class="compText">s</p></div>'
    with patch("pawgrab.engine.search_provider.AsyncSession", return_value=_session_returning(html)):
        out = await _engine_yahoo("test", 5, SearchParams())
    assert out.results[0]["url"] == "https://y.example/p"


# --- instant answers ----------------------------------------------------------


async def test_fetch_instant_answers():
    payload = {
        "Answer": "42",
        "AbstractText": "The meaning of life.",
        "Heading": "Life",
        "AbstractURL": "https://en.wikipedia.org/wiki/Life",
        "AbstractSource": "Wikipedia",
    }
    with patch("pawgrab.engine.search_provider.settings") as s:
        s.search_instant_answers = True
        with patch("pawgrab.engine.search_provider.AsyncSession", return_value=_json_session(payload)):
            answers, infoboxes = await _fetch_instant_answers("meaning of life")
    assert "42" in answers
    assert infoboxes[0]["title"] == "Life"
    assert infoboxes[0]["url"].endswith("/Life")


async def test_instant_answers_disabled():
    with patch("pawgrab.engine.search_provider.settings") as s:
        s.search_instant_answers = False
        assert await _fetch_instant_answers("x") == ([], [])


# --- engine selection / categories -------------------------------------------


def test_select_engines_general_auto():
    with patch("pawgrab.engine.search_provider.settings") as s:
        s.google_search_api_key = ""
        assert _select_engines("auto", "general") == ["duckduckgo", "bing", "mojeek"]


def test_select_engines_news_only_bing():
    with patch("pawgrab.engine.search_provider.settings") as s:
        s.google_search_api_key = ""
        # DDG doesn't serve news -> restricted to Bing.
        assert _select_engines("duckduckgo", "news") == ["bing"]


# --- public API + dispatch ----------------------------------------------------


async def test_search_web_returns_urls():
    with patch("pawgrab.engine.search_provider.settings") as s:
        s.search_provider = "duckduckgo"
        s.google_search_api_key = ""
        s.search_engine_timeout = 12.0
        s.search_instant_answers = False
        with patch(
            "pawgrab.engine.search_provider._engine_duckduckgo",
            new_callable=AsyncMock,
            return_value=EngineResult(results=[_r("https://a.com", "A", ""), _r("https://b.com", "B", "")]),
        ):
            assert await search_web("q") == ["https://a.com", "https://b.com"]


async def test_search_envelope_full_shape():
    with patch("pawgrab.engine.search_provider.settings") as s:
        s.search_provider = "auto"
        s.google_search_api_key = ""
        s.search_engine_timeout = 12.0
        s.search_instant_answers = False
        with (
            patch(
                "pawgrab.engine.search_provider._engine_duckduckgo",
                new_callable=AsyncMock,
                return_value=EngineResult(results=[_r("https://shared.com", "Shared", "x")], suggestions=["a"]),
            ),
            patch(
                "pawgrab.engine.search_provider._engine_bing",
                new_callable=AsyncMock,
                return_value=EngineResult(results=[_r("https://shared.com", "Shared", "x")], corrections=["fix"]),
            ),
            patch("pawgrab.engine.search_provider._engine_mojeek", new_callable=AsyncMock, return_value=EngineResult()),
        ):
            env = await search("q", 5)
    assert env["results"][0]["link"] == "https://shared.com"
    assert set(env["results"][0]["engines"]) == {"duckduckgo", "bing"}
    assert env["suggestions"] == ["a"] and env["corrections"] == ["fix"]
    assert "mojeek" in env["unresponsive_engines"]
    assert env["category"] == "general" and env["page"] == 1
    assert any(t["engine"] == "bing" for t in env["timings"])


async def test_search_engine_timeout_reported_unresponsive():
    import asyncio

    async def _slow(*a, **k):
        await asyncio.sleep(1)
        return EngineResult()

    with patch("pawgrab.engine.search_provider.settings") as s:
        s.search_provider = "duckduckgo"
        s.google_search_api_key = ""
        s.search_engine_timeout = 0.01
        s.search_instant_answers = False
        with patch("pawgrab.engine.search_provider._engine_duckduckgo", side_effect=_slow):
            env = await search("q")
    assert env["unresponsive_engines"] == ["duckduckgo"]


def test_search_result_dataclass_defaults():
    r = SearchResult(url="https://x.com")
    assert r.engines == set() and r.positions == [] and r.score == 0.0 and r.type == "general"


async def test_search_structured_is_results_list():
    with patch("pawgrab.engine.search_provider.settings") as s:
        s.search_provider = "duckduckgo"
        s.google_search_api_key = ""
        s.search_engine_timeout = 12.0
        s.search_instant_answers = False
        with patch(
            "pawgrab.engine.search_provider._engine_duckduckgo",
            new_callable=AsyncMock,
            return_value=EngineResult(results=[_r("https://a.com", "A", "snip")]),
        ):
            items = await search_structured("q")
    assert items[0]["link"] == "https://a.com" and items[0]["position"] == 1
