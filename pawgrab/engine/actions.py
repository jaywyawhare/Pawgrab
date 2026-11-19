"""Shared page-action executor.

One implementation of the click/scroll/type/wait/form/key action switch, reused by
the scrape fetcher (``engine.fetcher``), batch, and the live interact endpoint
(``api.interact``). Kept separate so there is exactly one place that knows how to
drive a Patchright/Playwright page.
"""

from __future__ import annotations

import asyncio

import structlog

from pawgrab.config import settings

logger = structlog.get_logger()


async def run_actions(page: object, actions: list, timeout: int) -> list[str]:
    """Execute page actions sequentially, returning any warnings."""
    from pawgrab.models.scrape import ActionType

    warnings: list[str] = []
    per_action_timeout = max(timeout // (len(actions) + 1), 5_000)
    humanize = settings.humanize_interactions
    for i, action in enumerate(actions):
        try:
            match action.type:
                case ActionType.CLICK:
                    if humanize:
                        box = await page.locator(action.selector).first.bounding_box(timeout=per_action_timeout)
                        if box:
                            from pawgrab.engine.humanize import human_click

                            await human_click(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                        else:
                            await page.click(action.selector, timeout=per_action_timeout)
                    else:
                        await page.click(action.selector, timeout=per_action_timeout)
                case ActionType.TYPE:
                    if humanize:
                        from pawgrab.engine.humanize import human_type

                        await human_type(page, action.selector, action.text, timeout=per_action_timeout)
                    else:
                        await page.fill(action.selector, action.text, timeout=per_action_timeout)
                case ActionType.SCROLL:
                    direction = -1 if action.direction == "up" else 1
                    px = (action.amount or 500) * direction
                    await page.evaluate(f"window.scrollBy(0, {px})")
                case ActionType.WAIT:
                    await asyncio.sleep((action.amount or 0) / 1000)
                case ActionType.WAIT_FOR:
                    await page.wait_for_selector(action.selector, timeout=per_action_timeout)
                case ActionType.SCREENSHOT:
                    warnings.append(f"Action {i} (screenshot): use the top-level screenshot=true option; standalone screenshot actions are not returned")
                case ActionType.EXECUTE_JS:
                    await asyncio.wait_for(
                        page.evaluate(action.text),
                        timeout=per_action_timeout / 1000,
                    )
                case ActionType.SELECT:
                    await page.select_option(action.selector, action.text, timeout=per_action_timeout)
                case ActionType.CHECK:
                    await page.check(action.selector, timeout=per_action_timeout)
                case ActionType.UNCHECK:
                    await page.uncheck(action.selector, timeout=per_action_timeout)
                case ActionType.FOCUS:
                    await page.focus(action.selector, timeout=per_action_timeout)
                case ActionType.HOVER:
                    await page.hover(action.selector, timeout=per_action_timeout)
                case ActionType.FILL_FORM:
                    for field_selector, value in (action.form_data or {}).items():
                        await page.fill(field_selector, value, timeout=per_action_timeout)
                case ActionType.SUBMIT_FORM:
                    form = page.locator(action.selector)
                    submit_btn = form.locator('[type="submit"], button[type="submit"], input[type="submit"]')
                    if await submit_btn.count() > 0:
                        await submit_btn.first.click(timeout=per_action_timeout)
                    else:
                        await page.evaluate("(sel) => document.querySelector(sel).submit()", action.selector)
                case ActionType.PRESS_KEY:
                    if action.selector:
                        await page.press(action.selector, action.text, timeout=per_action_timeout)
                    else:
                        await page.keyboard.press(action.text)
        except Exception as exc:
            msg = f"Action {i} ({action.type.value}) failed: {exc}"
            logger.warning("action_failed", action=action.type.value, index=i, error=str(exc))
            warnings.append(msg)
    return warnings
