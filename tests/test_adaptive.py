"""Tests for self-healing CSS extraction (adaptive selectors)."""

from pawgrab.engine.adaptive import (
    DiskSignatureStore,
    RedisSignatureStore,
    element_signature,
    find_by_signature,
    get_adaptive_store,
    score_candidate,
)
from pawgrab.engine.extractors import CSSExtractor
from pawgrab.utils.text import make_soup

PAGE_V1 = """
<html><body>
  <main>
    <h1 id="headline" class="title primary">Original Title</h1>
    <span class="price" data-qa="amount">$29.99</span>
    <a class="buy" href="/cart/42">Buy now</a>
  </main>
</body></html>
"""

# Same page after a redesign: class names changed, element wrapped, order shifted.
PAGE_V2 = """
<html><body>
  <section>
    <div class="hero">
      <a class="cta-button" href="/cart/42">Buy now</a>
      <h1 id="headline" class="headline-xl brand">Original Title</h1>
      <span class="amount-lg" data-qa="amount">$29.99</span>
    </div>
  </section>
</body></html>
"""

SELECTORS = {
    "title": "h1.title",
    "price": {"selector": "span.price", "attribute": None},
    "link": {"selector": "a.buy", "attribute": "href"},
}


def test_element_signature_captures_stable_fields():
    soup = make_soup(PAGE_V1)
    sig = element_signature(soup.select_one("h1"))
    assert sig["tag"] == "h1"
    assert sig["stable"]["id"] == "headline"
    assert "title" in sig["classes"]
    assert sig["text"] == "Original Title"


def test_find_by_signature_relocates_after_redesign():
    v1 = make_soup(PAGE_V1)
    sig = element_signature(v1.select_one("h1"))
    v2 = make_soup(PAGE_V2)
    # The v1 selector class is gone in v2, but the signature should still find it.
    assert v2.select("h1.title") == []
    found = find_by_signature(v2, sig, min_score=0.6)
    assert found is not None
    assert found.get("id") == "headline"


def test_score_candidate_prefers_the_true_element():
    v1 = make_soup(PAGE_V1)
    sig = element_signature(v1.select_one("span.price"))
    v2 = make_soup(PAGE_V2)
    true_el = v2.select_one("span.amount-lg")
    other = v2.select_one("h1")
    assert score_candidate(true_el, sig) > score_candidate(other, sig)


def test_extractor_learns_signatures_on_hit():
    ext = CSSExtractor(SELECTORS, adaptive=True)
    data = ext.extract(PAGE_V1)
    assert data[0]["title"] == "Original Title"
    assert data[0]["price"] == "$29.99"
    assert data[0]["link"] == "/cart/42"
    assert ext.healed == []
    assert set(ext.learned_signatures) == {"title", "price", "link"}


def test_extractor_heals_with_prior_signatures():
    learn = CSSExtractor(SELECTORS, adaptive=True)
    learn.extract(PAGE_V1)
    signatures = learn.learned_signatures

    heal = CSSExtractor(SELECTORS, adaptive=True, signatures=signatures, min_score=0.6)
    data = heal.extract(PAGE_V2)
    assert data[0]["title"] == "Original Title"
    assert data[0]["price"] == "$29.99"
    assert data[0]["link"] == "/cart/42"
    assert set(heal.healed) == {"title", "price", "link"}


def test_no_healing_when_adaptive_disabled():
    ext = CSSExtractor(SELECTORS, adaptive=False, signatures={"title": {"tag": "h1"}})
    data = ext.extract(PAGE_V2)
    assert data[0]["title"] is None
    assert ext.healed == []


def test_heal_returns_none_below_threshold():
    learn = CSSExtractor(SELECTORS, adaptive=True)
    learn.extract(PAGE_V1)
    # An impossibly high threshold means no candidate qualifies.
    heal = CSSExtractor(SELECTORS, adaptive=True, signatures=learn.learned_signatures, min_score=0.999)
    data = heal.extract(PAGE_V2)
    assert data[0]["title"] is None
    assert heal.healed == []


async def test_store_in_memory_lru_round_trip():
    store = RedisSignatureStore()  # redis unavailable in tests → falls back to cache only
    sigs = {"title": {"tag": "h1", "text": "x"}}
    await store.save("example.com", sigs)
    assert await store.load("example.com") == sigs


def test_get_adaptive_store_selects_backend(monkeypatch):
    import pawgrab.engine.adaptive as adaptive_mod
    from pawgrab.config import settings

    adaptive_mod._store = None
    monkeypatch.setattr(settings, "adaptive_store_backend", "disk")
    assert isinstance(get_adaptive_store(), DiskSignatureStore)
    adaptive_mod._store = None
    monkeypatch.setattr(settings, "adaptive_store_backend", "redis")
    assert isinstance(get_adaptive_store(), RedisSignatureStore)
    adaptive_mod._store = None
