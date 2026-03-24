"""Plugin system for extending Pawgrab's scraping pipeline."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

import structlog

logger = structlog.get_logger()


class PluginHook:
    """A named hook point in the pipeline that plugins can register to."""

    __slots__ = ("_name", "_handlers")

    def __init__(self, name: str):
        self._name = name
        self._handlers: list[Callable] = []

    def register(self, handler: Callable):
        self._handlers.append(handler)

    async def fire(self, **kwargs) -> dict[str, Any]:
        """Fire all registered handlers, passing kwargs. Returns merged results."""
        result = {}
        for handler in self._handlers:
            try:
                out = handler(**kwargs)
                if hasattr(out, "__await__"):
                    out = await out
                if isinstance(out, dict):
                    result.update(out)
            except Exception as exc:
                logger.warning("plugin_hook_error", hook=self._name, handler=handler.__name__, error=str(exc))
        return result


class PluginManager:
    """Manages plugin registration and lifecycle."""

    def __init__(self):
        self._plugins: dict[str, Any] = {}
        self._hooks: dict[str, PluginHook] = {}
        self._register_default_hooks()

    def _register_default_hooks(self):
        """Register the standard pipeline hooks."""
        for name in (
            "before_fetch", "after_fetch",
            "before_extract", "after_extract",
            "before_convert", "after_convert",
            "on_error", "on_challenge",
            "before_cache_store", "after_cache_hit",
        ):
            self._hooks[name] = PluginHook(name)

    def get_hook(self, name: str) -> PluginHook:
        if name not in self._hooks:
            self._hooks[name] = PluginHook(name)
        return self._hooks[name]

    def register_plugin(self, name: str, plugin: Any):
        """Register a plugin. The plugin should have methods matching hook names."""
        self._plugins[name] = plugin
        for hook_name, hook in self._hooks.items():
            handler = getattr(plugin, hook_name, None)
            if callable(handler):
                hook.register(handler)
                logger.info("plugin_hook_registered", plugin=name, hook=hook_name)

    def load_plugin(self, module_path: str) -> bool:
        """Load a plugin from a Python module path (e.g. 'mypackage.my_plugin')."""
        try:
            mod = importlib.import_module(module_path)
            plugin_class = getattr(mod, "Plugin", None)
            if plugin_class is None:
                logger.warning("plugin_no_Plugin_class", module=module_path)
                return False
            instance = plugin_class()
            name = getattr(instance, "name", module_path)
            self.register_plugin(name, instance)
            logger.info("plugin_loaded", name=name, module=module_path)
            return True
        except Exception as exc:
            logger.error("plugin_load_failed", module=module_path, error=str(exc))
            return False

    async def fire(self, hook_name: str, **kwargs) -> dict[str, Any]:
        """Fire a hook by name."""
        hook = self._hooks.get(hook_name)
        if hook:
            return await hook.fire(**kwargs)
        return {}

    @property
    def plugins(self) -> dict[str, Any]:
        return dict(self._plugins)

    @property
    def hooks(self) -> list[str]:
        return list(self._hooks.keys())


# Global singleton
plugin_manager = PluginManager()


def load_plugins_from_config():
    """Load plugins specified in PAWGRAB_PLUGINS env var."""
    from pawgrab.config import settings
    if not settings.plugins:
        return
    for module_path in settings.plugins.split(","):
        module_path = module_path.strip()
        if module_path:
            plugin_manager.load_plugin(module_path)
