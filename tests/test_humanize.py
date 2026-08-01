"""Tests for human-like input emulation."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from pawgrab.engine.humanize import (
    _bezier,
    human_click,
    human_move,
    human_scroll,
    human_type,
)


def _fake_page(scroll_heights=None):
    page = MagicMock()
    page.mouse = MagicMock()
    page.mouse.move = AsyncMock()
    page.mouse.down = AsyncMock()
    page.mouse.up = AsyncMock()
    page.mouse.wheel = AsyncMock()
    page.mouse.click = AsyncMock()
    page.keyboard = MagicMock()
    page.keyboard.type = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.click = AsyncMock()
    page.fill = AsyncMock()
    heights = iter(scroll_heights or [])

    async def _evaluate(expr):
        if "scrollHeight" in expr:
            return next(heights, 100)
        if "scrollY" in expr:
            return 100  # already at bottom -> loop converges fast
        return None

    page.evaluate = AsyncMock(side_effect=_evaluate)
    return page


def test_bezier_endpoints():
    p0, p1, p2, p3 = (0, 0), (1, 1), (2, 2), (3, 3)
    assert _bezier(p0, p1, p2, p3, 0.0) == pytest.approx((0, 0))
    assert _bezier(p0, p1, p2, p3, 1.0) == pytest.approx((3, 3))


async def test_human_move_samples_curve():
    page = _fake_page()
    await human_move(page, 400, 300)
    # A curved path issues many incremental moves, ending on the target.
    assert page.mouse.move.await_count >= 10
    last = page.mouse.move.await_args_list[-1].args
    assert last == (400, 300)


async def test_human_click_presses_and_releases():
    page = _fake_page()
    await human_click(page, 200, 150)
    assert page.mouse.down.await_count == 1
    assert page.mouse.up.await_count == 1


async def test_human_click_falls_back_on_error():
    page = _fake_page()
    page.mouse.down = AsyncMock(side_effect=RuntimeError("no button"))
    await human_click(page, 10, 10)  # must not raise
    page.mouse.click.assert_awaited()


async def test_human_type_types_each_character():
    page = _fake_page()
    await human_type(page, "#q", "hi")
    typed = "".join(c.args[0] for c in page.keyboard.type.await_args_list if c.args)
    # Every real character appears (typo corrections may add extras).
    assert "h" in typed and "i" in typed


async def test_human_type_fallback_to_fill():
    page = _fake_page()
    page.keyboard.type = AsyncMock(side_effect=RuntimeError("unsupported"))
    await human_type(page, "#q", "abc")  # must not raise
    page.fill.assert_awaited()


async def test_human_scroll_uses_wheel_and_resets():
    page = _fake_page(scroll_heights=[100, 100, 100])
    await human_scroll(page, max_scrolls=3)
    assert page.mouse.wheel.await_count >= 1
    # Final call resets to top.
    assert any("scrollTo(0, 0)" in (c.args[0] if c.args else "") for c in page.evaluate.await_args_list)
