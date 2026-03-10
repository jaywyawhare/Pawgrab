"""Shared ARQ connection pool."""

from __future__ import annotations

import asyncio
import re

from arq import create_pool
from arq.connections import RedisSettings

from pawgrab.config import settings

JOB_ID_RE = re.compile(r"^[a-f0-9]{12}$")

_arq_pool = None
_arq_lock = asyncio.Lock()


async def get_arq_pool():
    global _arq_pool
    if _arq_pool is None:
        async with _arq_lock:
            if _arq_pool is None:
                redis_settings = RedisSettings.from_dsn(settings.redis_url)
                _arq_pool = await create_pool(redis_settings)
    return _arq_pool
