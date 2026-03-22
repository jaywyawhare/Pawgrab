"""Lifecycle hooks for the scrape pipeline."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Callable, Coroutine

import structlog

logger = structlog.get_logger()

HookCallable = Callable[..., Coroutine[Any, Any, None]]

VALID_HOOKS = frozenset({
    "before_fetch",
    "after_fetch",
    "before_extract",
    "after_extract",
    "on_error",
})


class HookManager:
    """Manage lifecycle hooks for the scrape pipeline."""

    def __init__(self):
        self._hooks: dict[str, list[HookCallable]] = defaultdict(list)

    def register(self, event: str, callback: HookCallable) -> None:
        """Register a hook callback for an event.

        Args:
            event: One of the VALID_HOOKS event names.
            callback: An async callable to invoke when the event fires.
        """
        if event not in VALID_HOOKS:
            raise ValueError(f"Unknown hook event: {event}. Valid: {VALID_HOOKS}")
        self._hooks[event].append(callback)

    def unregister(self, event: str, callback: HookCallable) -> None:
        """Remove a specific callback from an event."""
        if event in self._hooks:
            self._hooks[event] = [h for h in self._hooks[event] if h is not callback]

    def clear(self, event: str | None = None) -> None:
        """Clear all hooks for an event, or all hooks if event is None."""
        if event:
            self._hooks.pop(event, None)
        else:
            self._hooks.clear()

    async def fire(self, event: str, **kwargs: Any) -> None:
        """Fire all hooks for an event, passing kwargs to each.

        Hooks run concurrently. Exceptions are logged but don't stop
        other hooks or the main pipeline.
        """
        hooks = self._hooks.get(event, [])
        if not hooks:
            return

        tasks = [self._safe_call(hook, event, **kwargs) for hook in hooks]
        await asyncio.gather(*tasks)

    @staticmethod
    async def _safe_call(hook: HookCallable, event_name: str, **kwargs: Any) -> None:
        """Call a hook, catching and logging any exceptions."""
        try:
            await hook(**kwargs)
        except Exception as exc:
            logger.warning("hook_failed", hook_event=event_name, hook_name=hook.__name__, error=str(exc))

    @property
    def registered_events(self) -> list[str]:
        """Return list of events that have registered hooks."""
        return [e for e, hooks in self._hooks.items() if hooks]
