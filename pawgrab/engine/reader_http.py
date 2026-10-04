"""Shared single-shot fetch for the structured readers: SSRF-guarded, browser-impersonated."""

from __future__ import annotations

from curl_cffi.requests import AsyncSession

from pawgrab.engine.antibot import random_impersonate, stealth_headers
from pawgrab.utils.url_safety import assert_public_url

READER_TIMEOUT = 15


async def reader_get(url: str, *, timeout: int = READER_TIMEOUT, cookies: dict | None = None, headers: dict | None = None):
    """GET a reader target through the stealth stack after an SSRF check.

    Returns the curl_cffi response so callers choose ``.text`` or ``.json()``.
    """
    await assert_public_url(url)
    hdrs = stealth_headers()
    if headers:
        hdrs.update(headers)
    async with AsyncSession(impersonate=random_impersonate(), timeout=timeout) as session:
        return await session.get(url, headers=hdrs, cookies=cookies, timeout=timeout, allow_redirects=True)
