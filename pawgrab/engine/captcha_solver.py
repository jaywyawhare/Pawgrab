"""CAPTCHA solving integration via external services (2Captcha, CapSolver)."""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from pawgrab.config import settings

logger = structlog.get_logger()


class CaptchaSolver:
    """Async CAPTCHA solver supporting multiple provider backends."""

    def __init__(self):
        self._provider = settings.captcha_provider
        self._api_key = settings.captcha_api_key

    @property
    def available(self) -> bool:
        return bool(self._api_key and self._provider)

    async def solve_recaptcha_v2(self, site_key: str, page_url: str) -> str | None:
        """Solve reCAPTCHA v2 and return the token."""
        if not self.available:
            return None
        if self._provider == "2captcha":
            return await self._solve_2captcha("recaptcha", {
                "googlekey": site_key, "pageurl": page_url,
            })
        elif self._provider == "capsolver":
            return await self._solve_capsolver("ReCaptchaV2TaskProxyLess", {
                "websiteKey": site_key, "websiteURL": page_url,
            })
        return None

    async def solve_hcaptcha(self, site_key: str, page_url: str) -> str | None:
        """Solve hCaptcha and return the token."""
        if not self.available:
            return None
        if self._provider == "2captcha":
            return await self._solve_2captcha("hcaptcha", {
                "sitekey": site_key, "pageurl": page_url,
            })
        elif self._provider == "capsolver":
            return await self._solve_capsolver("HCaptchaTaskProxyLess", {
                "websiteKey": site_key, "websiteURL": page_url,
            })
        return None

    async def solve_turnstile(self, site_key: str, page_url: str) -> str | None:
        """Solve Cloudflare Turnstile and return the token."""
        if not self.available:
            return None
        if self._provider == "2captcha":
            return await self._solve_2captcha("turnstile", {
                "sitekey": site_key, "pageurl": page_url,
            })
        elif self._provider == "capsolver":
            return await self._solve_capsolver("AntiTurnstileTaskProxyLess", {
                "websiteKey": site_key, "websiteURL": page_url,
            })
        return None

    async def _solve_2captcha(self, method: str, params: dict) -> str | None:
        """Submit and poll 2Captcha API."""
        try:
            from curl_cffi.requests import AsyncSession
            async with AsyncSession() as session:
                submit_data = {"key": self._api_key, "method": method, "json": 1, **params}
                resp = await session.post("https://2captcha.com/in.php", data=submit_data)
                result = resp.json()
                if result.get("status") != 1:
                    logger.warning("2captcha_submit_failed", error=result.get("request"))
                    return None

                task_id = result["request"]

                for _ in range(24):  # 24 × 5 s = 120 s max
                    await asyncio.sleep(5)
                    resp = await session.get(
                        f"https://2captcha.com/res.php?key={self._api_key}&action=get&id={task_id}&json=1"
                    )
                    result = resp.json()
                    if result.get("status") == 1:
                        logger.info("2captcha_solved", method=method)
                        return result["request"]
                    if result.get("request") != "CAPCHA_NOT_READY":
                        logger.warning("2captcha_error", error=result.get("request"))
                        return None

                logger.warning("2captcha_timeout", method=method)
                return None
        except Exception as exc:
            logger.error("2captcha_failed", error=str(exc))
            return None

    async def _solve_capsolver(self, task_type: str, params: dict) -> str | None:
        """Submit and poll CapSolver API."""
        try:
            from curl_cffi.requests import AsyncSession
            async with AsyncSession() as session:
                payload = {
                    "clientKey": self._api_key,
                    "task": {"type": task_type, **params},
                }
                resp = await session.post(
                    "https://api.capsolver.com/createTask",
                    json=payload,
                )
                result = resp.json()
                if result.get("errorId", 0) != 0:
                    logger.warning("capsolver_submit_failed", error=result.get("errorDescription"))
                    return None

                task_id = result["taskId"]

                for _ in range(24):  # 24 × 5 s = 120 s max
                    await asyncio.sleep(5)
                    resp = await session.post(
                        "https://api.capsolver.com/getTaskResult",
                        json={"clientKey": self._api_key, "taskId": task_id},
                    )
                    result = resp.json()
                    status = result.get("status")
                    if status == "ready":
                        solution = result.get("solution", {})
                        token = solution.get("gRecaptchaResponse") or solution.get("token")
                        logger.info("capsolver_solved", task_type=task_type)
                        return token
                    if status == "failed":
                        logger.warning("capsolver_failed", error=result.get("errorDescription"))
                        return None

                logger.warning("capsolver_timeout", task_type=task_type)
                return None
        except Exception as exc:
            logger.error("capsolver_failed", error=str(exc))
            return None


_solver: CaptchaSolver | None = None


def get_solver() -> CaptchaSolver:
    global _solver
    if _solver is None:
        _solver = CaptchaSolver()
    return _solver


async def solve_captcha_on_page(page, url: str, challenge_type: str) -> bool:
    """Attempt to solve a CAPTCHA on a Playwright page.

    Extracts the site key from the page, solves via external service,
    and injects the token back into the page.
    """
    solver = get_solver()
    if not solver.available:
        return False

    try:
        site_key = await page.evaluate("""() => {
            // reCAPTCHA
            const recaptcha = document.querySelector('[data-sitekey]');
            if (recaptcha) return {type: 'recaptcha', key: recaptcha.getAttribute('data-sitekey')};
            // hCaptcha
            const hcaptcha = document.querySelector('[data-sitekey]');
            if (hcaptcha) return {type: 'hcaptcha', key: hcaptcha.getAttribute('data-sitekey')};
            // Turnstile
            const turnstile = document.querySelector('[data-sitekey]');
            if (turnstile) return {type: 'turnstile', key: turnstile.getAttribute('data-sitekey')};
            // Try window.turnstile
            if (window._cf_chl_opt && window._cf_chl_opt.chlApiSitekey)
                return {type: 'turnstile', key: window._cf_chl_opt.chlApiSitekey};
            return null;
        }""")

        if not site_key:
            logger.debug("no_captcha_sitekey_found", url=url)
            return False

        captcha_type = site_key["type"]
        key = site_key["key"]

        token = None
        if captcha_type == "recaptcha":
            token = await solver.solve_recaptcha_v2(key, url)
        elif captcha_type == "hcaptcha":
            token = await solver.solve_hcaptcha(key, url)
        elif captcha_type == "turnstile":
            token = await solver.solve_turnstile(key, url)

        if not token:
            return False

        await page.evaluate(f"""(token) => {{
            // reCAPTCHA
            const textarea = document.getElementById('g-recaptcha-response');
            if (textarea) {{ textarea.value = token; textarea.style.display = 'block'; }}
            // hCaptcha
            const hTextarea = document.querySelector('[name="h-captcha-response"]');
            if (hTextarea) {{ hTextarea.value = token; }}
            // Turnstile
            const cfInput = document.querySelector('[name="cf-turnstile-response"]');
            if (cfInput) {{ cfInput.value = token; }}
            // Trigger callbacks
            if (window.___grecaptcha_cfg) {{
                const clients = window.___grecaptcha_cfg.clients;
                for (const id in clients) {{
                    const client = clients[id];
                    if (client && client.callback) client.callback(token);
                }}
            }}
        }}""", token)

        await asyncio.sleep(1)
        logger.info("captcha_solved_and_injected", url=url, type=captcha_type)
        return True

    except Exception as exc:
        logger.warning("captcha_solve_failed", url=url, error=str(exc))
        return False
