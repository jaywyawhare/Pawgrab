"""Human-like input emulation for the Playwright path.

CloakBrowser's ``humanize=True`` replaces instant Playwright ``click``/``fill``
with motion that carries realistic entropy: Bezier-curve mouse paths with
overshoot, per-character typing with occasional self-correcting typos, and
accelerate->cruise->decelerate scrolling.  Behavioural anti-bot layers (mouse
entropy, keystroke-timing analysis) score these far higher than teleport clicks
and zero-delay ``fill`` calls, which are a dead giveaway of automation.

All helpers degrade gracefully: any Playwright error falls back to the plain
call so humanization never costs a page.
"""

from __future__ import annotations

import asyncio
import random

_MOVE_STEPS = (18, 34)  # min/max sampled points along a mouse path
_STEP_DELAY_S = (0.006, 0.018)  # per-step dwell
_CLICK_HOLD_MS = (55, 130)  # button press->release
_TYPE_DELAY_MS = (55, 155)  # per-character
_TYPO_CHANCE = 0.04  # probability of a self-corrected mistype per char
_THINK_PAUSE_CHANCE = 0.06  # probability of a longer "thinking" pause per char


def _bezier(p0, p1, p2, p3, t):
    """Cubic Bezier interpolation at parameter ``t`` in [0, 1]."""
    mt = 1.0 - t
    a = mt * mt * mt
    b = 3 * mt * mt * t
    c = 3 * mt * t * t
    d = t * t * t
    x = a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0]
    y = a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]
    return x, y


def _control_points(start, end, rng):
    """Two random control points bowing the path off the straight line."""
    (x0, y0), (x1, y1) = start, end
    dx, dy = x1 - x0, y1 - y0
    # Perpendicular offset scaled to the travel distance (curved, not straight).
    spread = (abs(dx) + abs(dy)) * 0.18 + 8
    c1 = (x0 + dx * 0.3 + rng.uniform(-spread, spread), y0 + dy * 0.3 + rng.uniform(-spread, spread))
    c2 = (x0 + dx * 0.7 + rng.uniform(-spread, spread), y0 + dy * 0.7 + rng.uniform(-spread, spread))
    return c1, c2


async def human_move(page, x: float, y: float, *, start: tuple[float, float] | None = None) -> None:
    """Move the mouse to ``(x, y)`` along a curved, variable-speed path."""
    rng = random
    origin = start or (rng.uniform(0, 60), rng.uniform(0, 60))
    end = (x, y)
    c1, c2 = _control_points(origin, end, rng)
    steps = rng.randint(*_MOVE_STEPS)
    try:
        for i in range(1, steps + 1):
            # Ease-in-out so the pointer accelerates then settles on the target.
            t = i / steps
            t = t * t * (3 - 2 * t)
            px, py = _bezier(origin, c1, c2, end, t)
            await page.mouse.move(px, py)
            await asyncio.sleep(rng.uniform(*_STEP_DELAY_S))
        # Small overshoot-and-correct on ~40% of moves.
        if rng.random() < 0.4:
            await page.mouse.move(x + rng.uniform(-3, 3), y + rng.uniform(-3, 3))
            await asyncio.sleep(rng.uniform(*_STEP_DELAY_S))
            await page.mouse.move(x, y)
    except Exception:
        # Fall back to a direct move if the incremental path is rejected.
        try:
            await page.mouse.move(x, y)
        except Exception:
            pass


async def human_click(page, x: float, y: float) -> None:
    """Move to ``(x, y)`` with a human path, then click with a realistic hold."""
    await human_move(page, x, y)
    hold = random.uniform(*_CLICK_HOLD_MS) / 1000.0
    try:
        await page.mouse.down()
        await asyncio.sleep(hold)
        await page.mouse.up()
    except Exception:
        try:
            await page.mouse.click(x, y, delay=random.randint(*_CLICK_HOLD_MS))
        except Exception:
            pass


async def human_type(page, selector: str, text: str, *, timeout: int = 10_000) -> None:
    """Type ``text`` into ``selector`` character-by-character with jitter and typos."""
    rng = random
    try:
        await page.click(selector, timeout=timeout)
    except Exception:
        pass
    kb = page.keyboard
    for ch in text:
        # Occasional mistype followed by a backspace correction.
        if rng.random() < _TYPO_CHANCE and ch.isalpha():
            wrong = chr(ord(ch) + rng.choice((-1, 1)))
            try:
                await kb.type(wrong, delay=rng.uniform(*_TYPE_DELAY_MS))
                await asyncio.sleep(rng.uniform(0.08, 0.2))
                await kb.press("Backspace")
            except Exception:
                pass
        try:
            await kb.type(ch, delay=rng.uniform(*_TYPE_DELAY_MS))
        except Exception:
            # Fall back to a single fill if per-char typing is unsupported.
            try:
                await page.fill(selector, text, timeout=timeout)
            except Exception:
                pass
            return
        if rng.random() < _THINK_PAUSE_CHANCE:
            await asyncio.sleep(rng.uniform(0.25, 0.7))


async def human_scroll(page, *, max_scrolls: int = 30) -> None:
    """Scroll to the bottom with accelerate->cruise->decelerate wheel steps."""
    rng = random
    try:
        prev_height = -1
        for _ in range(max_scrolls):
            height = await page.evaluate("document.body.scrollHeight")
            pos = await page.evaluate("window.scrollY + window.innerHeight")
            if pos >= height - 2:
                if height == prev_height:
                    break
                prev_height = height
            # A burst of small wheel deltas that ramp up then ease off.
            for delta in (120, 220, 340, 260, 140):
                await page.mouse.wheel(0, delta + rng.randint(-30, 30))
                await asyncio.sleep(rng.uniform(0.05, 0.14))
            await asyncio.sleep(rng.uniform(0.2, 0.5))
        await page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        # Fall back to the deterministic JS scroller on any failure.
        try:
            from pawgrab.engine.browser import _SCROLL_TO_BOTTOM_JS

            await page.evaluate(_SCROLL_TO_BOTTOM_JS)
        except Exception:
            pass
