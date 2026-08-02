import pytest

from pawgrab.engine.plugins import PluginHook, PluginManager


class TestPluginHook:
    @pytest.fixture
    def hook(self):
        return PluginHook("test_hook")

    async def test_no_handlers(self, hook):
        assert await hook.fire(url="https://example.com") == {}

    async def test_sync_handler(self, hook):
        called = []

        def handler(**kwargs):
            called.append(kwargs)
            return {"key": "value"}

        hook.register(handler)
        result = await hook.fire(url="test")
        assert called[0]["url"] == "test"
        assert result["key"] == "value"

    async def test_async_handler(self, hook):
        called = []

        async def handler(**kwargs):
            called.append(kwargs)
            return {"async_key": "async_value"}

        hook.register(handler)
        result = await hook.fire(x=1)
        assert called[0]["x"] == 1
        assert result["async_key"] == "async_value"

    async def test_multiple_handlers_merge(self, hook):
        hook.register(lambda **kw: {"a": 1})
        hook.register(lambda **kw: {"b": 2})
        result = await hook.fire()
        assert result == {"a": 1, "b": 2}

    async def test_failing_handler_does_not_crash(self, hook):
        def bad(**kw):
            raise RuntimeError("boom")

        hook.register(bad)
        hook.register(lambda **kw: {"survived": True})
        result = await hook.fire()
        assert result["survived"] is True

    async def test_non_dict_return_ignored(self, hook):
        hook.register(lambda **kw: "string_result")
        assert await hook.fire() == {}


class TestPluginManager:
    @pytest.fixture
    def manager(self):
        return PluginManager()

    def test_default_hooks(self, manager):
        for name in ("before_fetch", "after_fetch", "on_error", "before_extract", "after_extract"):
            assert name in manager.hooks

    def test_get_hook_existing(self, manager):
        assert isinstance(manager.get_hook("before_fetch"), PluginHook)

    def test_get_hook_creates_new(self, manager):
        hook = manager.get_hook("custom_hook")
        assert isinstance(hook, PluginHook)
        assert "custom_hook" in manager.hooks

    def test_register_plugin(self, manager):
        class MyPlugin:
            name = "myplugin"

            def before_fetch(self, **kwargs):
                pass

        manager.register_plugin("myplugin", MyPlugin())
        assert "myplugin" in manager.plugins

    async def test_fire_calls_plugin_handler(self, manager):
        results = []

        class MyPlugin:
            name = "counter"

            def before_fetch(self, **kwargs):
                results.append(kwargs.get("url"))

        manager.register_plugin("counter", MyPlugin())
        await manager.fire("before_fetch", url="https://example.com")
        assert "https://example.com" in results

    async def test_fire_unknown_hook_returns_empty(self, manager):
        assert await manager.fire("nonexistent_hook", x=1) == {}

    def test_load_plugin_no_plugin_class(self, manager):
        import sys
        import types

        mod = types.ModuleType("fake_plugin_noclass")
        sys.modules["fake_plugin_noclass"] = mod
        assert manager.load_plugin("fake_plugin_noclass") is False
        del sys.modules["fake_plugin_noclass"]

    def test_load_plugin_module_not_found(self, manager):
        assert manager.load_plugin("nonexistent.module.path") is False

    def test_load_plugin_success(self, manager):
        import sys
        import types

        mod = types.ModuleType("fake_plugin_ok")

        class Plugin:
            name = "loaded_plugin"

        mod.Plugin = Plugin
        sys.modules["fake_plugin_ok"] = mod
        assert manager.load_plugin("fake_plugin_ok") is True
        assert "loaded_plugin" in manager.plugins
        del sys.modules["fake_plugin_ok"]
