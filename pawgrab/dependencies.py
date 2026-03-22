"""Dependency injection for shared resources."""

from __future__ import annotations

import asyncio

from pawgrab.engine.browser import BrowserPool
from pawgrab.engine.proxy_pool import ProxyPool

_browser_pool: BrowserPool | None = None
_pool_lock = asyncio.Lock()

_proxy_pool: ProxyPool | None = None
_proxy_lock = asyncio.Lock()


async def get_browser_pool() -> BrowserPool:
    global _browser_pool
    if _browser_pool is None:
        async with _pool_lock:
            if _browser_pool is None:
                _browser_pool = BrowserPool()
                await _browser_pool.start()
    return _browser_pool


async def shutdown_browser_pool():
    global _browser_pool
    if _browser_pool is not None:
        await _browser_pool.stop()
        _browser_pool = None


async def get_proxy_pool() -> ProxyPool:
    global _proxy_pool
    if _proxy_pool is None:
        async with _proxy_lock:
            if _proxy_pool is None:
                _proxy_pool = ProxyPool()
                await _proxy_pool.start()
    return _proxy_pool


async def shutdown_proxy_pool():
    global _proxy_pool
    if _proxy_pool is not None:
        await _proxy_pool.stop()
        _proxy_pool = None


async def try_browser_pool() -> BrowserPool | None:
    try:
        return await get_browser_pool()
    except Exception:
        return None


async def try_proxy_pool() -> ProxyPool | None:
    try:
        return await get_proxy_pool()
    except Exception:
        return None
