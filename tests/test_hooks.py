"""Tests for Phase 6: Lifecycle hooks."""

import pytest

from pawgrab.engine.hooks import HookManager


class TestHookManager:
    @pytest.fixture
    def manager(self):
        return HookManager()

    async def test_register_and_fire(self, manager):
        called = []

        async def hook(**kwargs):
            called.append(kwargs)

        manager.register("before_fetch", hook)
        await manager.fire("before_fetch", url="https://example.com")
        assert len(called) == 1
        assert called[0]["url"] == "https://example.com"

    async def test_multiple_hooks(self, manager):
        results = []

        async def hook1(**kwargs):
            results.append("hook1")

        async def hook2(**kwargs):
            results.append("hook2")

        manager.register("after_fetch", hook1)
        manager.register("after_fetch", hook2)
        await manager.fire("after_fetch", url="test")
        assert "hook1" in results
        assert "hook2" in results

    async def test_hook_error_doesnt_crash(self, manager):
        async def bad_hook(**kwargs):
            raise ValueError("boom")

        async def good_hook(**kwargs):
            pass

        manager.register("on_error", bad_hook)
        manager.register("on_error", good_hook)
        # Should not raise
        await manager.fire("on_error", error="test")

    def test_invalid_event_raises(self, manager):
        async def hook(**kwargs):
            pass

        with pytest.raises(ValueError, match="Unknown hook event"):
            manager.register("invalid_event", hook)

    async def test_unregister(self, manager):
        called = []

        async def hook(**kwargs):
            called.append(True)

        manager.register("before_fetch", hook)
        manager.unregister("before_fetch", hook)
        await manager.fire("before_fetch")
        assert len(called) == 0

    def test_clear(self, manager):
        async def hook(**kwargs):
            pass

        manager.register("before_fetch", hook)
        manager.register("after_fetch", hook)
        manager.clear("before_fetch")
        assert "before_fetch" not in manager.registered_events
        assert "after_fetch" in manager.registered_events

    def test_clear_all(self, manager):
        async def hook(**kwargs):
            pass

        manager.register("before_fetch", hook)
        manager.register("after_fetch", hook)
        manager.clear()
        assert manager.registered_events == []

    async def test_fire_no_hooks(self, manager):
        # Should not raise
        await manager.fire("before_fetch", url="test")
