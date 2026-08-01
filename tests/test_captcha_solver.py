from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pawgrab.engine.captcha_solver import CaptchaSolver, get_solver


def _make_solver(provider="", api_key=""):
    s = CaptchaSolver.__new__(CaptchaSolver)
    s._provider = provider
    s._api_key = api_key
    return s


class TestAvailability:
    @pytest.mark.parametrize(
        "provider,api_key",
        [
            ("", ""),
            ("", "somekey"),
            ("2captcha", ""),
        ],
    )
    def test_unavailable(self, provider, api_key):
        assert _make_solver(provider, api_key).available is False

    def test_available_with_key_and_provider(self):
        assert _make_solver("2captcha", "somekey").available is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,args",
    [
        ("solve_recaptcha_v2", ("site_key", "https://example.com")),
        ("solve_hcaptcha", ("site_key", "https://example.com")),
        ("solve_turnstile", ("site_key", "https://example.com")),
    ],
)
async def test_returns_none_when_unavailable(method, args):
    result = await getattr(_make_solver(), method)(*args)
    assert result is None


class TestTwoCaptcha:
    @pytest.fixture
    def solver(self):
        return _make_solver("2captcha", "test_api_key")

    @pytest.mark.asyncio
    async def test_solve_recaptcha_success(self, solver):
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = AsyncMock(return_value=MagicMock(json=lambda: {"status": 1, "request": "task123"}))
        mock_session.get = AsyncMock(return_value=MagicMock(json=lambda: {"status": 1, "request": "token_value"}))

        with patch("pawgrab.engine.captcha_solver.asyncio.sleep", new_callable=AsyncMock):
            with patch("curl_cffi.requests.AsyncSession", return_value=mock_session):
                result = await solver.solve_recaptcha_v2("site_key", "https://example.com")

        assert result == "token_value"

    @pytest.mark.asyncio
    async def test_submit_failure_returns_none(self, solver):
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = AsyncMock(return_value=MagicMock(json=lambda: {"status": 0, "request": "ERROR_WRONG_KEY"}))

        with patch("curl_cffi.requests.AsyncSession", return_value=mock_session):
            result = await solver.solve_recaptcha_v2("site_key", "https://example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_exception_returns_none(self, solver):
        with patch("curl_cffi.requests.AsyncSession", side_effect=Exception("network error")):
            assert await solver._solve_2captcha("recaptcha", {}) is None


class TestCapSolver:
    @pytest.fixture
    def solver(self):
        return _make_solver("capsolver", "test_api_key")

    @pytest.mark.asyncio
    async def test_solve_success(self, solver):
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = AsyncMock(
            side_effect=[
                MagicMock(json=lambda: {"errorId": 0, "taskId": "task_abc"}),
                MagicMock(json=lambda: {"status": "ready", "solution": {"gRecaptchaResponse": "capsolver_token"}}),
            ]
        )

        with patch("pawgrab.engine.captcha_solver.asyncio.sleep", new_callable=AsyncMock):
            with patch("curl_cffi.requests.AsyncSession", return_value=mock_session):
                result = await solver.solve_recaptcha_v2("site_key", "https://example.com")

        assert result == "capsolver_token"

    @pytest.mark.asyncio
    async def test_submit_error_returns_none(self, solver):
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = AsyncMock(return_value=MagicMock(json=lambda: {"errorId": 1, "errorDescription": "Invalid API key"}))

        with patch("curl_cffi.requests.AsyncSession", return_value=mock_session):
            assert await solver._solve_capsolver("ReCaptchaV2TaskProxyLess", {}) is None

    @pytest.mark.asyncio
    async def test_exception_returns_none(self, solver):
        with patch("curl_cffi.requests.AsyncSession", side_effect=RuntimeError("fail")):
            assert await solver._solve_capsolver("HCaptchaTaskProxyLess", {}) is None


def test_get_solver_returns_singleton():
    import pawgrab.engine.captcha_solver as mod

    mod._solver = None
    s1 = get_solver()
    s2 = get_solver()
    assert s1 is s2
    mod._solver = None


async def test_solve_cookie_challenge_capsolver_datadome():
    """DataDome routes to the CapSolver DatadomeSliderTask and returns its cookie."""
    from unittest.mock import AsyncMock

    from pawgrab.engine.captcha_solver import CaptchaSolver

    solver = CaptchaSolver()
    solver._provider = "capsolver"
    solver._api_key = "k"
    solver._solve_capsolver = AsyncMock(return_value="datadome=COOKIEVAL")

    out = await solver.solve_cookie_challenge("datadome", page_url="https://x.com", captcha_url="https://captcha-delivery.com/c", user_agent="UA")
    assert out == "datadome=COOKIEVAL"
    task_type = solver._solve_capsolver.await_args.args[0]
    assert task_type == "DatadomeSliderTask"


async def test_solve_cookie_challenge_unsupported_vendor_returns_none():
    """A vendor the provider has no task for returns None (no fabrication)."""
    from pawgrab.engine.captcha_solver import CaptchaSolver

    solver = CaptchaSolver()
    solver._provider = "capsolver"
    solver._api_key = "k"
    # PerimeterX has no generic CapSolver task -> None, cleanly.
    assert await solver.solve_cookie_challenge("perimeterx", page_url="https://x.com") is None


async def test_solve_cookie_challenge_2captcha_awswaf():
    from unittest.mock import AsyncMock

    from pawgrab.engine.captcha_solver import CaptchaSolver

    solver = CaptchaSolver()
    solver._provider = "2captcha"
    solver._api_key = "k"
    solver._solve_2captcha = AsyncMock(return_value="TOKEN123")
    out = await solver.solve_cookie_challenge("aws_waf", page_url="https://x.com", user_agent="UA")
    assert out == "TOKEN123"
    assert solver._solve_2captcha.await_args.args[0] == "amazon_waf"


async def test_solve_cookie_challenge_on_page_sets_cookie_and_reloads():
    from unittest.mock import AsyncMock, MagicMock, patch

    from pawgrab.engine.captcha_solver import solve_cookie_challenge_on_page

    page = MagicMock()
    page.evaluate = AsyncMock(side_effect=["UA-string", "https://captcha-delivery.com/x"])
    page.context = MagicMock()
    page.context.add_cookies = AsyncMock()
    page.reload = AsyncMock()
    page.content = AsyncMock(return_value="<html><body>real content</body></html>")

    fake_solver = MagicMock()
    fake_solver.available = True
    fake_solver.solve_cookie_challenge = AsyncMock(return_value="datadome=XYZ")

    with patch("pawgrab.engine.captcha_solver.get_solver", return_value=fake_solver):
        ok = await solve_cookie_challenge_on_page(page, "https://x.com/p", "datadome")

    assert ok is True
    page.context.add_cookies.assert_awaited_once()
    cookie = page.context.add_cookies.await_args.args[0][0]
    assert cookie["name"] == "datadome" and cookie["value"] == "XYZ"
    page.reload.assert_awaited_once()
