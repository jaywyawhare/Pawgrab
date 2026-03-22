"""Memory-adaptive concurrency control."""

from __future__ import annotations

import asyncio

import structlog

from pawgrab.config import settings

logger = structlog.get_logger()


_mem_fallback_warned = False


def _get_memory_percent() -> float:
    """Get current system memory usage as a percentage.

    Tries /proc/meminfo (Linux/Docker), then psutil if installed.
    Returns 0.0 with a one-time warning if neither is available.
    """
    global _mem_fallback_warned

    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        mem_info = {}
        for line in lines:
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0].rstrip(":")
                mem_info[key] = int(parts[1])

        total = mem_info.get("MemTotal", 1)
        available = mem_info.get("MemAvailable", total)
        return ((total - available) / total) * 100
    except FileNotFoundError:
        pass

    try:
        import psutil
        return psutil.virtual_memory().percent
    except ImportError:
        pass

    if not _mem_fallback_warned:
        _mem_fallback_warned = True
        logger.warning(
            "memory_monitoring_unavailable",
            hint="Install psutil for memory-adaptive concurrency on non-Linux systems",
        )
    return 0.0


class MemoryAdaptiveDispatcher:
    """Dynamically adjusts concurrency based on system memory usage.

    When memory exceeds the threshold, concurrency is reduced.
    When memory recovers, concurrency is gradually restored.
    """

    def __init__(
        self,
        min_concurrency: int | None = None,
        max_concurrency: int | None = None,
        memory_threshold: float | None = None,
        check_interval: float = 5.0,
    ):
        self._min = min_concurrency or settings.min_concurrency
        self._max = max_concurrency or settings.max_concurrency
        self._threshold = memory_threshold or settings.memory_threshold_percent
        self._check_interval = check_interval
        self._current_concurrency = self._max
        self._semaphore = asyncio.Semaphore(self._max)
        self._monitor_task: asyncio.Task | None = None
        self._running = False

    @property
    def current_concurrency(self) -> int:
        return self._current_concurrency

    async def start(self) -> None:
        """Start the memory monitoring loop."""
        if self._running:
            return
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(
            "dispatcher_started",
            min_concurrency=self._min,
            max_concurrency=self._max,
            memory_threshold=self._threshold,
        )

    async def stop(self) -> None:
        """Stop the memory monitoring loop."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("dispatcher_stopped")

    async def acquire(self) -> None:
        """Acquire a concurrency slot (blocks if at capacity)."""
        await self._semaphore.acquire()

    def release(self) -> None:
        """Release a concurrency slot."""
        self._semaphore.release()

    async def _adjust_semaphore(self, new_level: int) -> None:
        """Adjust semaphore capacity without replacing it (preserves waiters)."""
        diff = new_level - self._current_concurrency
        if diff > 0:
            for _ in range(diff):
                self._semaphore.release()
        elif diff < 0:
            # Non-blocking drain: asyncio.timeout(0) raises TimeoutError instead of blocking.
            for _ in range(-diff):
                try:
                    async with asyncio.timeout(0):
                        await self._semaphore.acquire()
                except TimeoutError:
                    break
        self._current_concurrency = new_level

    async def _monitor_loop(self) -> None:
        """Periodically check memory and adjust concurrency."""
        while self._running:
            try:
                mem_pct = _get_memory_percent()
                if mem_pct > self._threshold:
                    new_level = max(self._min, self._current_concurrency - 1)
                    if new_level < self._current_concurrency:
                        await self._adjust_semaphore(new_level)
                        logger.warning(
                            "dispatcher_scaling_down",
                            memory_percent=round(mem_pct, 1),
                            concurrency=new_level,
                        )
                elif mem_pct < self._threshold - 10:
                    new_level = min(self._max, self._current_concurrency + 1)
                    if new_level > self._current_concurrency:
                        await self._adjust_semaphore(new_level)
                        logger.info(
                            "dispatcher_scaling_up",
                            memory_percent=round(mem_pct, 1),
                            concurrency=new_level,
                        )
            except Exception as exc:
                logger.debug("dispatcher_monitor_error", error=str(exc))

            await asyncio.sleep(self._check_interval)

    def get_stats(self) -> dict:
        """Return current dispatcher statistics."""
        return {
            "current_concurrency": self._current_concurrency,
            "min_concurrency": self._min,
            "max_concurrency": self._max,
            "memory_threshold_percent": self._threshold,
            "memory_usage_percent": round(_get_memory_percent(), 1),
        }
