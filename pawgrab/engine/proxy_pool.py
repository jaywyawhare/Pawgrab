"""Proxy pool with rotation, health checking, and auto-eviction."""

from __future__ import annotations

import asyncio
import enum
import random
import time
from dataclasses import dataclass, field

import structlog

from pawgrab.config import settings

logger = structlog.get_logger()

# Health-check endpoints (rotate through them to avoid rate limits)
_HEALTH_CHECK_URLS = [
    "https://ifconfig.me/ip",
    "https://api.ipify.org",
    "https://icanhazip.com",
]

_RECENT_WINDOW = 300.0  # 5 minutes


class RotationPolicy(enum.Enum):
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    LEAST_USED = "least_used"


@dataclass
class ProxyEntry:
    url: str
    ok: bool = True
    speed: float = 0.0  # EMA latency in seconds

    # Lifetime counters
    offered: int = 0
    succeed: int = 0
    timeouts: int = 0
    failures: int = 0
    reanimated: int = 0

    # Recent window counters (reset every _RECENT_WINDOW seconds)
    recent_offered: int = 0
    recent_succeed: int = 0
    recent_timeouts: int = 0
    recent_failures: int = 0
    recent_window_start: float = field(default_factory=time.monotonic)

    # Backoff: monotonic timestamp after which proxy can be retried
    reanimate_after: float | None = None

    def _reset_window_if_needed(self) -> None:
        now = time.monotonic()
        if now - self.recent_window_start >= _RECENT_WINDOW:
            self.recent_offered = 0
            self.recent_succeed = 0
            self.recent_timeouts = 0
            self.recent_failures = 0
            self.recent_window_start = now

    def mark_success(self, speed: float | None = None) -> None:
        self._reset_window_if_needed()
        self.ok = True
        self.reanimate_after = None
        self.succeed += 1
        self.recent_succeed += 1
        if speed is not None:
            # Exponential moving average (alpha=0.3)
            self.speed = self.speed * 0.7 + speed * 0.3 if self.speed else speed

    def mark_failure(self, is_timeout: bool = False, backoff_seconds: float = 60.0) -> None:
        self._reset_window_if_needed()
        self.ok = False
        self.failures += 1
        self.recent_failures += 1
        if is_timeout:
            self.timeouts += 1
            self.recent_timeouts += 1
        self.reanimate_after = time.monotonic() + backoff_seconds

    def should_skip(self, offer_limit: int) -> bool:
        self._reset_window_if_needed()
        # Auto-reanimate when backoff expires
        if self.reanimate_after is not None and time.monotonic() >= self.reanimate_after:
            self.ok = True
            self.reanimate_after = None
            self.reanimated += 1
        if not self.ok:
            return True
        if self.recent_offered >= offer_limit:
            return True
        return False

    def should_evict(self, failure_threshold: int) -> bool:
        self._reset_window_if_needed()
        return self.recent_succeed == 0 and self.recent_failures >= failure_threshold

    def snapshot(self) -> dict:
        self._reset_window_if_needed()
        return {
            "url": self.url,
            "ok": self.ok,
            "speed": round(self.speed, 4),
            "offered": self.offered,
            "succeed": self.succeed,
            "timeouts": self.timeouts,
            "failures": self.failures,
            "reanimated": self.reanimated,
            "recent_offered": self.recent_offered,
            "recent_succeed": self.recent_succeed,
            "recent_timeouts": self.recent_timeouts,
            "recent_failures": self.recent_failures,
        }


class ProxyPool:
    def __init__(self) -> None:
        self._entries: list[ProxyEntry] = []
        self._lock = asyncio.Lock()
        self._rotation_index: int = 0
        self._eviction_task: asyncio.Task | None = None
        self._health_task: asyncio.Task | None = None
        self._policy = RotationPolicy.ROUND_ROBIN

    async def start(self) -> None:
        try:
            self._policy = RotationPolicy(settings.proxy_rotation_policy)
        except ValueError:
            self._policy = RotationPolicy.ROUND_ROBIN

        urls: list[str] = []
        if settings.proxy_urls:
            urls = [p.strip() for p in settings.proxy_urls.split(",") if p.strip()]
        if not urls and settings.proxy_url:
            urls = [settings.proxy_url]

        for url in urls:
            self.add_proxy(url)

        if self._entries:
            self._eviction_task = asyncio.create_task(self._eviction_loop())
            if settings.proxy_health_check:
                self._health_task = asyncio.create_task(self._health_check_loop())
            logger.info("proxy_pool_started", count=len(self._entries), policy=self._policy.value)

    async def stop(self) -> None:
        for task in (self._eviction_task, self._health_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._eviction_task = None
        self._health_task = None
        logger.info("proxy_pool_stopped", count=len(self._entries))

    def add_proxy(self, url: str) -> bool:
        """Add a proxy (idempotent). Returns True if added, False if duplicate."""
        for entry in self._entries:
            if entry.url == url:
                return False
        self._entries.append(ProxyEntry(url=url))
        # Start background tasks if this is the first proxy added at runtime
        if len(self._entries) == 1 and self._eviction_task is None:
            self._eviction_task = asyncio.create_task(self._eviction_loop())
            if settings.proxy_health_check and self._health_task is None:
                self._health_task = asyncio.create_task(self._health_check_loop())
        return True

    def remove_proxy(self, url: str) -> bool:
        """Remove a proxy. Returns True if removed."""
        for i, entry in enumerate(self._entries):
            if entry.url == url:
                self._entries.pop(i)
                return True
        return False

    async def get_proxy(self) -> ProxyEntry | None:
        """Get the next proxy according to the rotation policy.

        Caller MUST call entry.mark_success() or entry.mark_failure() after use.
        Returns None if the pool is empty or all proxies are unhealthy.
        """
        async with self._lock:
            if not self._entries:
                return None

            n = len(self._entries)
            offer_limit = settings.proxy_offer_limit

            if self._policy == RotationPolicy.RANDOM:
                candidates = [e for e in self._entries if not e.should_skip(offer_limit)]
                if not candidates:
                    return None
                entry = random.choice(candidates)
                entry.offered += 1
                entry.recent_offered += 1
                return entry

            if self._policy == RotationPolicy.LEAST_USED:
                candidates = [e for e in self._entries if not e.should_skip(offer_limit)]
                if not candidates:
                    return None
                entry = min(candidates, key=lambda e: e.offered)
                entry.offered += 1
                entry.recent_offered += 1
                return entry

            # Default: round_robin
            for _ in range(n):
                entry = self._entries[self._rotation_index % n]
                self._rotation_index += 1
                if not entry.should_skip(offer_limit):
                    entry.offered += 1
                    entry.recent_offered += 1
                    return entry

            return None

    def snapshot(self) -> list[dict]:
        return [e.snapshot() for e in self._entries]

    def pool_stats(self) -> dict:
        active = sum(1 for e in self._entries if e.ok)
        evicted = sum(1 for e in self._entries if not e.ok)
        speeds = [e.speed for e in self._entries if e.ok and e.speed > 0]
        return {
            "total": len(self._entries),
            "active": active,
            "evicted": evicted,
            "avg_speed": round(sum(speeds) / len(speeds), 4) if speeds else 0.0,
            "policy": self._policy.value,
        }

    async def _eviction_loop(self) -> None:
        """Periodically soft-evict proxies that exceed the failure threshold."""
        while True:
            await asyncio.sleep(60)
            threshold = settings.proxy_evict_after_failures
            backoff = settings.proxy_backoff_seconds
            for entry in self._entries:
                if entry.ok and entry.should_evict(threshold):
                    entry.ok = False
                    entry.reanimate_after = time.monotonic() + backoff
                    logger.info("proxy_evicted", url=entry.url, recent_failures=entry.recent_failures)

    async def _health_check_loop(self) -> None:
        """Periodically check proxy health via IP-check endpoints."""
        while True:
            await asyncio.sleep(settings.proxy_health_check_interval)
            for entry in list(self._entries):
                check_url = random.choice(_HEALTH_CHECK_URLS)
                t0 = time.monotonic()
                try:
                    from curl_cffi.requests import AsyncSession
                    async with AsyncSession(proxy=entry.url, timeout=10) as session:
                        resp = await session.get(check_url, timeout=10)
                        if resp.status_code == 200:
                            latency = time.monotonic() - t0
                            entry.mark_success(speed=latency)
                            logger.info("proxy_health_ok", url=entry.url, latency=round(latency, 3))
                        else:
                            entry.mark_failure(backoff_seconds=settings.proxy_backoff_seconds)
                            logger.info("proxy_health_fail", url=entry.url, status=resp.status_code)
                except Exception as exc:
                    is_timeout = "timeout" in str(exc).lower()
                    entry.mark_failure(is_timeout=is_timeout, backoff_seconds=settings.proxy_backoff_seconds)
                    logger.info("proxy_health_error", url=entry.url, error=str(exc))
