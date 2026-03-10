"""Tests for page actions feature."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from pawgrab.models.scrape import ActionType, PageAction, ScrapeRequest


class TestPageActionModel:
    def test_click_requires_selector(self):
        with pytest.raises(ValidationError):
            PageAction(type=ActionType.CLICK)

    def test_click_valid(self):
        a = PageAction(type=ActionType.CLICK, selector="button.submit")
        assert a.selector == "button.submit"

    def test_type_requires_selector_and_text(self):
        with pytest.raises(ValidationError):
            PageAction(type=ActionType.TYPE, selector="input")
        with pytest.raises(ValidationError):
            PageAction(type=ActionType.TYPE, text="hello")

    def test_type_valid(self):
        a = PageAction(type=ActionType.TYPE, selector="input#name", text="Alice")
        assert a.text == "Alice"

    def test_scroll_requires_direction(self):
        with pytest.raises(ValidationError):
            PageAction(type=ActionType.SCROLL)

    def test_scroll_default_amount(self):
        a = PageAction(type=ActionType.SCROLL, direction="down")
        assert a.amount == 500

    def test_scroll_custom_amount(self):
        a = PageAction(type=ActionType.SCROLL, direction="up", amount=1000)
        assert a.amount == 1000

    def test_wait_requires_amount(self):
        with pytest.raises(ValidationError):
            PageAction(type=ActionType.WAIT)

    def test_wait_valid(self):
        a = PageAction(type=ActionType.WAIT, amount=2000)
        assert a.amount == 2000

    def test_wait_for_requires_selector(self):
        with pytest.raises(ValidationError):
            PageAction(type=ActionType.WAIT_FOR)

    def test_screenshot_no_fields_needed(self):
        a = PageAction(type=ActionType.SCREENSHOT)
        assert a.type == ActionType.SCREENSHOT

    def test_execute_js_requires_text(self):
        with pytest.raises(ValidationError):
            PageAction(type=ActionType.EXECUTE_JS)

    def test_execute_js_valid(self):
        a = PageAction(type=ActionType.EXECUTE_JS, text="return document.title")
        assert a.text == "return document.title"


class TestScrapeRequestActions:
    def test_actions_field_optional(self):
        req = ScrapeRequest(url="https://example.com")
        assert req.actions is None

    def test_actions_field_accepts_list(self):
        req = ScrapeRequest(
            url="https://example.com",
            actions=[
                {"type": "click", "selector": "button"},
                {"type": "wait", "amount": 1000},
            ],
        )
        assert len(req.actions) == 2
        assert req.actions[0].type == ActionType.CLICK


class TestExecuteActions:
    @pytest.fixture
    def mock_page(self):
        page = AsyncMock()
        page.click = AsyncMock()
        page.fill = AsyncMock()
        page.evaluate = AsyncMock()
        page.wait_for_selector = AsyncMock()
        page.screenshot = AsyncMock()
        return page

    async def test_click_action(self, mock_page):
        from pawgrab.engine.fetcher import _execute_actions

        actions = [PageAction(type=ActionType.CLICK, selector="button#go")]
        warnings = await _execute_actions(mock_page, actions, 30000)
        mock_page.click.assert_awaited_once()
        assert warnings == []

    async def test_type_action(self, mock_page):
        from pawgrab.engine.fetcher import _execute_actions

        actions = [PageAction(type=ActionType.TYPE, selector="input", text="hello")]
        warnings = await _execute_actions(mock_page, actions, 30000)
        mock_page.fill.assert_awaited_once_with("input", "hello", timeout=15000)

    async def test_scroll_down(self, mock_page):
        from pawgrab.engine.fetcher import _execute_actions

        actions = [PageAction(type=ActionType.SCROLL, direction="down", amount=300)]
        await _execute_actions(mock_page, actions, 30000)
        mock_page.evaluate.assert_awaited_once_with("window.scrollBy(0, 300)")

    async def test_scroll_up(self, mock_page):
        from pawgrab.engine.fetcher import _execute_actions

        actions = [PageAction(type=ActionType.SCROLL, direction="up", amount=200)]
        await _execute_actions(mock_page, actions, 30000)
        mock_page.evaluate.assert_awaited_once_with("window.scrollBy(0, -200)")

    async def test_wait_action(self, mock_page):
        from pawgrab.engine.fetcher import _execute_actions

        actions = [PageAction(type=ActionType.WAIT, amount=100)]
        with patch("pawgrab.engine.fetcher.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await _execute_actions(mock_page, actions, 30000)
            mock_sleep.assert_awaited_once_with(0.1)

    async def test_execute_js_action(self, mock_page):
        from pawgrab.engine.fetcher import _execute_actions

        actions = [PageAction(type=ActionType.EXECUTE_JS, text="return 42")]
        await _execute_actions(mock_page, actions, 30000)
        mock_page.evaluate.assert_awaited_once_with("return 42")

    async def test_action_error_returns_warning(self, mock_page):
        from pawgrab.engine.fetcher import _execute_actions

        mock_page.click.side_effect = Exception("Element not found")
        actions = [PageAction(type=ActionType.CLICK, selector="missing")]
        warnings = await _execute_actions(mock_page, actions, 30000)
        assert len(warnings) == 1
        assert "failed" in warnings[0].lower()

    async def test_actions_force_browser_path(self):
        """When actions are present and browser pool exists, browser path is forced."""
        from pawgrab.engine.fetcher import fetch_page

        mock_pool = AsyncMock()
        mock_page = AsyncMock()
        mock_pool.acquire.return_value = mock_page
        mock_page.goto.return_value = MagicMock(status=200, headers={})
        mock_page.content.return_value = "<html><body>ok</body></html>"
        mock_page.url = "https://example.com"

        actions = [PageAction(type=ActionType.WAIT, amount=100)]
        with patch("pawgrab.engine.fetcher.asyncio.sleep", new_callable=AsyncMock):
            with patch("pawgrab.engine.fetcher.detect_challenge") as mock_detect:
                mock_detect.return_value = MagicMock(detected=False)
                result = await fetch_page(
                    "https://example.com",
                    browser_pool=mock_pool,
                    actions=actions,
                )
        assert result.used_browser is True

    async def test_actions_without_browser_pool_uses_curl(self):
        """Without browser pool, actions are ignored and curl path is used."""
        from pawgrab.engine.fetcher import fetch_page

        actions = [PageAction(type=ActionType.CLICK, selector="button")]
        with patch("pawgrab.engine.fetcher._fetch_with_curl") as mock_curl:
            mock_curl.return_value = MagicMock(
                html="<html>ok</html>",
                status_code=200,
                url="https://example.com",
                cookies={},
                resp_headers={},
                challenge=None,
                content_bytes=None,
                action_warnings=[],
            )
            with patch("pawgrab.engine.fetcher.needs_js_rendering", return_value=False):
                result = await fetch_page(
                    "https://example.com",
                    actions=actions,
                    # no browser_pool
                )
        # Without browser pool, falls through to curl
        assert mock_curl.called
