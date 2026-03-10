"""Tests for rate limiter."""

from pawgrab.utils.rate_limiter import _limiters, get_limiter


def test_get_limiter_creates_per_domain():
    _limiters.clear()
    l1 = get_limiter("https://example.com/page1")
    l2 = get_limiter("https://example.com/page2")
    assert l1 is l2

    l3 = get_limiter("https://other.com/page")
    assert l3 is not l1
    _limiters.clear()


def test_lru_eviction():
    _limiters.clear()
    from pawgrab.utils import rate_limiter

    old_max = rate_limiter._MAX_DOMAINS
    rate_limiter._MAX_DOMAINS = 3
    try:
        get_limiter("https://a.com")
        get_limiter("https://b.com")
        get_limiter("https://c.com")
        get_limiter("https://d.com")  # should evict a.com
        assert len(_limiters) == 3
        assert "a.com" not in _limiters
        assert "d.com" in _limiters
    finally:
        rate_limiter._MAX_DOMAINS = old_max
        _limiters.clear()
