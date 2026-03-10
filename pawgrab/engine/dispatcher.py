"""Memory-adaptive dispatcher for dynamic concurrency control.

Monitors system memory and adjusts the number of concurrent browser
instances to prevent OOM kills. Scales down when memory usage is high,
scales back up when it recovers.
"""

from __future__ import annotations

import asyncio

import structlog

from pawgrab.config import settings

logger = structlog.get_logger()


def _get_memory_percent() -> float:
    """Get current system memory usage as a percentage."""
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
    except Exception:
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

    async def _monitor_loop(self) -> None:
        """Periodically check memory and adjust concurrency."""
        while self._running:
            try:
                mem_pct = _get_memory_percent()
                if mem_pct > self._threshold:
                    new_level = max(self._min, self._current_concurrency - 1)
                    if new_level < self._current_concurrency:
                        self._current_concurrency = new_level
                        self._semaphore = asyncio.Semaphore(new_level)
                        logger.warning(
                            "dispatcher_scaling_down",
                            memory_percent=round(mem_pct, 1),
                            concurrency=new_level,
                        )
                elif mem_pct < self._threshold - 10:
                    new_level = min(self._max, self._current_concurrency + 1)
                    if new_level > self._current_concurrency:
                        self._current_concurrency = new_level
                        self._semaphore = asyncio.Semaphore(new_level)
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
