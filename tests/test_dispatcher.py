"""Tests for Phase 6: Memory-adaptive dispatcher."""


from pawgrab.engine.dispatcher import MemoryAdaptiveDispatcher, _get_memory_percent


class TestMemoryAdaptiveDispatcher:
    def test_initial_concurrency(self):
        d = MemoryAdaptiveDispatcher(min_concurrency=1, max_concurrency=5)
        assert d.current_concurrency == 5

    async def test_acquire_release(self):
        d = MemoryAdaptiveDispatcher(min_concurrency=1, max_concurrency=2)
        await d.acquire()
        d.release()

    def test_get_stats(self):
        d = MemoryAdaptiveDispatcher(min_concurrency=1, max_concurrency=5, memory_threshold=80.0)
        stats = d.get_stats()
        assert stats["min_concurrency"] == 1
        assert stats["max_concurrency"] == 5
        assert stats["memory_threshold_percent"] == 80.0
        assert "memory_usage_percent" in stats

    async def test_start_stop(self):
        d = MemoryAdaptiveDispatcher(
            min_concurrency=1, max_concurrency=3,
            check_interval=0.1,
        )
        await d.start()
        assert d.current_concurrency == 3
        await d.stop()


class TestGetMemoryPercent:
    def test_returns_float(self):
        result = _get_memory_percent()
        assert isinstance(result, float)
        assert 0.0 <= result <= 100.0
