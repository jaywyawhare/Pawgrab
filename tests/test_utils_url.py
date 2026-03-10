"""Tests for URL utilities."""

from pawgrab.utils.url import get_base_url, get_domain, is_same_domain, normalize_url, resolve_url


def test_get_domain():
    assert get_domain("https://example.com/path") == "example.com"
    assert get_domain("https://sub.example.com:8080/path") == "sub.example.com:8080"


def test_get_base_url():
    assert get_base_url("https://example.com/path?q=1") == "https://example.com"
    assert get_base_url("http://example.com:8080/path") == "http://example.com:8080"


def test_normalize_url():
    # Trailing slash normalization
    url1 = normalize_url("https://example.com/path/")
    url2 = normalize_url("https://example.com/path")
    assert url1 == url2
    # Fragment removal
    assert "#section" not in normalize_url("https://example.com/path#section")


def test_resolve_url():
    assert resolve_url("https://example.com/page", "/other") == "https://example.com/other"
    assert resolve_url("https://example.com/page", "https://other.com") == "https://other.com"


def test_is_same_domain():
    assert is_same_domain("https://example.com/a", "https://example.com/b") is True
    assert is_same_domain("https://other.com/a", "https://example.com/b") is False
