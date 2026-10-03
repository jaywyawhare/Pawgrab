"""Tests for shared SSRF protection."""

from unittest.mock import patch

import pytest

from pawgrab.config import settings
from pawgrab.utils.url_safety import (
    SSRFError,
    assert_public_url,
    is_safe_url,
    redact_url_creds,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1:6379",
        "http://localhost/admin",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://[::1]/",
        "http://internal.corp/",
        "http://db.internal/",
        "file:///etc/passwd",
        "gopher://127.0.0.1/",
        "ftp://example.com/",
    ],
)
def test_unsafe_urls_rejected(url):
    assert is_safe_url(url, allow_private=False) is False


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/page",
        "http://8.8.8.8/",
        "https://sub.domain.co.uk/path?q=1",
    ],
)
def test_safe_urls_allowed(url):
    assert is_safe_url(url, allow_private=False) is True


def test_allow_private_override():
    assert is_safe_url("http://127.0.0.1/", allow_private=True) is True


async def test_assert_public_url_blocks_literal_metadata():
    with pytest.raises(SSRFError):
        await assert_public_url("http://169.254.169.254/")


async def test_assert_public_url_blocks_dns_rebind():

    with patch(
        "pawgrab.utils.url_safety._resolve",
        return_value=["10.1.2.3"],
    ):
        with pytest.raises(SSRFError):
            await assert_public_url("http://rebind.example.com/")


async def test_assert_public_url_allows_public_resolution():
    with patch("pawgrab.utils.url_safety._resolve", return_value=["93.184.216.34"]):
        await assert_public_url("http://example.com/")


async def test_assert_public_url_fails_open_on_resolution_error():
    with patch("pawgrab.utils.url_safety._resolve", side_effect=OSError("dns down")):
        await assert_public_url("http://example.com/")


async def test_disabled_protection_is_noop(monkeypatch):
    monkeypatch.setattr(settings, "ssrf_protection", False)
    await assert_public_url("http://169.254.169.254/")


def test_redact_url_creds():
    assert redact_url_creds("http://user:pass@proxy.example.com:8080/x") == "http://proxy.example.com:8080/x"
    assert redact_url_creds("http://proxy.example.com:8080") == "http://proxy.example.com:8080"
    assert "pass" not in redact_url_creds("socks5://u:secret@1.2.3.4:1080")
