"""Tests for engine.ranking (F2)."""

from unittest.mock import AsyncMock, patch

from pawgrab.engine.ranking import cosine, rank_documents, rank_urls, url_to_text


def test_url_to_text_extracts_slugs():
    text = url_to_text("https://shop.example.com/pricing/pro-plan?ref=home")
    assert "pricing" in text
    assert "pro" in text and "plan" in text


def test_rank_urls_orders_by_relevance():
    urls = [
        "https://example.com/blog/cats",
        "https://example.com/pricing",
        "https://example.com/about-us",
        "https://example.com/pricing/enterprise-plan",
    ]
    ranked = rank_urls("pricing plan", urls)
    top = [u for u, _ in ranked[:2]]
    assert "https://example.com/pricing/enterprise-plan" in top
    assert "https://example.com/pricing" in top
    # scores are descending
    scores = [s for _, s in ranked]
    assert scores == sorted(scores, reverse=True)


def test_rank_urls_empty():
    assert rank_urls("x", []) == []


def test_rank_documents_by_text():
    docs = [
        {"url": "a", "text": "the quick brown fox"},
        {"url": "b", "text": "pricing tiers and monthly cost breakdown"},
    ]
    ranked = rank_documents("monthly pricing cost", docs)
    assert ranked[0][0]["url"] == "b"


def test_cosine():
    assert cosine([1, 0], [1, 0]) == 1.0
    assert cosine([1, 0], [0, 1]) == 0.0
    assert cosine([], [1]) == 0.0


async def test_map_search_ranks_and_returns_scores(client):
    urls = [
        "https://example.com/about",
        "https://example.com/pricing-plans",
    ]
    with patch("pawgrab.api.map.discover_urls", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = (urls, "sitemap")
        resp = await client.post("/map", json={"url": "https://example.com", "search": "pricing"})
    data = resp.json()
    assert resp.status_code == 200
    assert data["urls"][0] == "https://example.com/pricing-plans"
    assert data["scores"] is not None
    assert len(data["scores"]) == len(data["urls"])


async def test_map_without_search_has_no_scores(client):
    with patch("pawgrab.api.map.discover_urls", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = (["https://example.com/a"], "sitemap")
        resp = await client.post("/map", json={"url": "https://example.com"})
    assert resp.json()["scores"] is None
