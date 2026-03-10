"""Per-domain async rate limiter with LRU eviction."""

from __future__ import annotations

from collections import OrderedDict

from aiolimiter import AsyncLimiter

from pawgrab.config import settings
from pawgrab.utils.url import get_domain

_MAX_DOMAINS = 1000
_limiters: OrderedDict[str, AsyncLimiter] = OrderedDict()


def get_limiter(url: str) -> AsyncLimiter:
    """Get or create a rate limiter for the URL's domain."""
    domain = get_domain(url)
    if domain in _limiters:
        _limiters.move_to_end(domain)
        return _limiters[domain]

    # Evict oldest entries if at capacity
    while len(_limiters) >= _MAX_DOMAINS:
        _limiters.popitem(last=False)

    rpm = settings.rate_limit_rpm
    _limiters[domain] = AsyncLimiter(rpm, 60)
    return _limiters[domain]


async def wait_for_slot(url: str) -> None:
    """Wait until a rate limit slot is available for this domain."""
    limiter = get_limiter(url)
    await limiter.acquire()
