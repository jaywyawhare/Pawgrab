"""Shared single-shot fetch for the structured readers: SSRF-guarded, browser-impersonated."""

from __future__ import annotations

from urllib.parse import urljoin

from curl_cffi.requests import AsyncSession

from pawgrab.config import settings
from pawgrab.engine.antibot import random_impersonate, stealth_headers
from pawgrab.utils.url_safety import assert_public_url

READER_TIMEOUT = 15
_REDIRECT_STATUS = {301, 302, 303, 307, 308}


async def reader_get(url: str, *, timeout: int = READER_TIMEOUT, cookies: dict | None = None, headers: dict | None = None):
    """GET a reader target through the stealth stack, re-checking SSRF on every redirect hop.

    curl_cffi's built-in redirect following would skip the SSRF guard, so redirects
    are followed manually and each hop is validated before it is fetched. Returns the
    curl_cffi response so callers choose ``.text`` or ``.json()``.
    """
    hdrs = stealth_headers()
    if headers:
        hdrs.update(headers)
    async with AsyncSession(impersonate=random_impersonate(), timeout=timeout) as session:
        current = url
        for _ in range(settings.max_redirects + 1):
            await assert_public_url(current)
            resp = await session.get(current, headers=hdrs, cookies=cookies, timeout=timeout, allow_redirects=False)
            location = resp.headers.get("location")
            if resp.status_code in _REDIRECT_STATUS and location:
                current = urljoin(current, location)
                continue
            return resp
        raise ValueError("too many redirects")
