"""CAPTCHA solving integration via external services (2Captcha, CapSolver)."""

from __future__ import annotations

import asyncio

import structlog

from pawgrab.config import settings

logger = structlog.get_logger()

# Per-request timeout for solver-provider HTTP calls. Without it a hung provider
# holds the browser page slot well past the intended 120 s poll budget.
_HTTP_TIMEOUT = 30


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
            return await self._solve_2captcha(
                "recaptcha",
                {
                    "googlekey": site_key,
                    "pageurl": page_url,
                },
            )
        elif self._provider == "capsolver":
            return await self._solve_capsolver(
                "ReCaptchaV2TaskProxyLess",
                {
                    "websiteKey": site_key,
                    "websiteURL": page_url,
                },
            )
        return None

    async def solve_hcaptcha(self, site_key: str, page_url: str) -> str | None:
        """Solve hCaptcha and return the token."""
        if not self.available:
            return None
        if self._provider == "2captcha":
            return await self._solve_2captcha(
                "hcaptcha",
                {
                    "sitekey": site_key,
                    "pageurl": page_url,
                },
            )
        elif self._provider == "capsolver":
            return await self._solve_capsolver(
                "HCaptchaTaskProxyLess",
                {
                    "websiteKey": site_key,
                    "websiteURL": page_url,
                },
            )
        return None

    async def solve_turnstile(self, site_key: str, page_url: str) -> str | None:
        """Solve Cloudflare Turnstile and return the token."""
        if not self.available:
            return None
        if self._provider == "2captcha":
            return await self._solve_2captcha(
                "turnstile",
                {
                    "sitekey": site_key,
                    "pageurl": page_url,
                },
            )
        elif self._provider == "capsolver":
            return await self._solve_capsolver(
                "AntiTurnstileTaskProxyLess",
                {
                    "websiteKey": site_key,
                    "websiteURL": page_url,
                },
            )
        return None

    # Cookie-based anti-bot vendors (DataDome / Imperva / AWS-WAF). These return a
    # cookie (or token) via the same 2Captcha/CapSolver backends used above; the
    # caller injects it and reloads. Vendors with no generic provider task type
    # (PerimeterX, Akamai — proxy-service based) return None rather than pretend.
    _CAPSOLVER_TASKS = {
        "datadome": "DatadomeSliderTask",
        "imperva": "AntiImpervaTask",
        "aws_waf": "AntiAwsWafTask",
    }
    _2CAPTCHA_METHODS = {
        "datadome": "datadome",
        "aws_waf": "amazon_waf",
    }

    async def solve_cookie_challenge(
        self,
        challenge_type: str,
        *,
        page_url: str,
        captcha_url: str | None = None,
        user_agent: str | None = None,
        proxy: str | None = None,
    ) -> str | None:
        """Solve a cookie-based anti-bot challenge; returns a cookie/token or None."""
        if not self.available:
            return None
        if self._provider == "capsolver":
            task_type = self._CAPSOLVER_TASKS.get(challenge_type)
            if not task_type:
                logger.info("capsolver_no_task_for_vendor", vendor=challenge_type)
                return None
            params: dict = {"websiteURL": page_url}
            if captcha_url:
                params["captchaUrl"] = captcha_url
            if user_agent:
                params["userAgent"] = user_agent
            if proxy:
                params["proxy"] = proxy
            return await self._solve_capsolver(task_type, params)
        if self._provider == "2captcha":
            method = self._2CAPTCHA_METHODS.get(challenge_type)
            if not method:
                logger.info("2captcha_no_method_for_vendor", vendor=challenge_type)
                return None
            params = {"pageurl": page_url}
            if captcha_url:
                params["captcha_url"] = captcha_url
            if user_agent:
                params["userAgent"] = user_agent
            if proxy:
                params["proxy"] = proxy
            return await self._solve_2captcha(method, params)
        return None

    async def _solve_2captcha(self, method: str, params: dict) -> str | None:
        """Submit and poll 2Captcha API."""
        try:
            from curl_cffi.requests import AsyncSession

            async with AsyncSession(timeout=_HTTP_TIMEOUT) as session:
                submit_data = {"key": self._api_key, "method": method, "json": 1, **params}
                resp = await session.post("https://2captcha.com/in.php", data=submit_data, timeout=_HTTP_TIMEOUT)
                result = resp.json()
                if result.get("status") != 1:
                    logger.warning("2captcha_submit_failed", error=result.get("request"))
                    return None

                task_id = result["request"]

                for _ in range(24):  # 24 × 5 s = 120 s max
                    await asyncio.sleep(5)
                    resp = await session.get(
                        f"https://2captcha.com/res.php?key={self._api_key}&action=get&id={task_id}&json=1",
                        timeout=_HTTP_TIMEOUT,
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

            async with AsyncSession(timeout=_HTTP_TIMEOUT) as session:
                payload = {
                    "clientKey": self._api_key,
                    "task": {"type": task_type, **params},
                }
                resp = await session.post(
                    "https://api.capsolver.com/createTask",
                    json=payload,
                    timeout=_HTTP_TIMEOUT,
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
                        timeout=_HTTP_TIMEOUT,
                    )
                    result = resp.json()
                    status = result.get("status")
                    if status == "ready":
                        solution = result.get("solution", {})
                        # Token-based (reCAPTCHA/hCaptcha/Turnstile/AWS-WAF) or
                        # cookie-based (DataDome/Imperva) solutions.
                        token = solution.get("gRecaptchaResponse") or solution.get("token") or solution.get("cookie")
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
            const keyOf = el => el && (el.getAttribute('data-sitekey') || el.dataset.sitekey);
            // hCaptcha — distinct class/attribute.
            const hEl = document.querySelector('.h-captcha[data-sitekey]');
            if (hEl) return {type: 'hcaptcha', key: keyOf(hEl)};
            const hAttr = document.querySelector('[data-hcaptcha-sitekey]');
            if (hAttr) return {type: 'hcaptcha', key: hAttr.getAttribute('data-hcaptcha-sitekey')};
            // Cloudflare Turnstile — distinct class or CF challenge global.
            const tEl = document.querySelector('.cf-turnstile[data-sitekey]');
            if (tEl) return {type: 'turnstile', key: keyOf(tEl)};
            if (window._cf_chl_opt && window._cf_chl_opt.chlApiSitekey)
                return {type: 'turnstile', key: window._cf_chl_opt.chlApiSitekey};
            // reCAPTCHA — g-recaptcha class or grecaptcha global.
            const rEl = document.querySelector('.g-recaptcha[data-sitekey]');
            if (rEl) return {type: 'recaptcha', key: keyOf(rEl)};
            // Bare [data-sitekey] fallback: disambiguate by nearby iframe host.
            const bare = document.querySelector('[data-sitekey]');
            if (bare) {
                const key = keyOf(bare);
                if (document.querySelector('iframe[src*="hcaptcha.com"]')) return {type: 'hcaptcha', key};
                if (document.querySelector('iframe[src*="challenges.cloudflare.com"]')) return {type: 'turnstile', key};
                return {type: 'recaptcha', key};
            }
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

        await page.evaluate(
            """(token) => {
            // reCAPTCHA
            const textarea = document.getElementById('g-recaptcha-response');
            if (textarea) { textarea.value = token; textarea.style.display = 'block'; }
            // hCaptcha
            const hTextarea = document.querySelector('[name="h-captcha-response"]');
            if (hTextarea) { hTextarea.value = token; }
            // Turnstile
            const cfInput = document.querySelector('[name="cf-turnstile-response"]');
            if (cfInput) { cfInput.value = token; }
            // Trigger callbacks
            if (window.___grecaptcha_cfg) {
                const clients = window.___grecaptcha_cfg.clients;
                for (const id in clients) {
                    const client = clients[id];
                    if (client && client.callback) client.callback(token);
                }
            }
        }""",
            token,
        )

        await asyncio.sleep(1)
        logger.info("captcha_solved_and_injected", url=url, type=captcha_type)
        return True

    except Exception as exc:
        logger.warning("captcha_solve_failed", url=url, error=str(exc))
        return False


# The challenge-script URL DataDome/Imperva embed (needed by the solver task).
_COOKIE_CHALLENGE_URL_JS = """() => {
    const sel = [
        'script[src*="captcha-delivery.com"]',
        'script[src*="datadome"]',
        'iframe[src*="captcha-delivery.com"]',
        'script[src*="imperva"]',
        'script[src*="incapsula"]',
    ];
    for (const s of sel) {
        const el = document.querySelector(s);
        if (el) return el.src;
    }
    return null;
}"""


async def solve_cookie_challenge_on_page(page, url: str, challenge_type: str, *, proxy: str | None = None) -> bool:
    """Solve a cookie-based anti-bot challenge (DataDome/Imperva/AWS-WAF) via the
    external solver, set the returned cookie on the context, and reload.

    Returns True if the challenge cleared. Vendors the configured provider has no
    task for (e.g. PerimeterX/Akamai) resolve to None and return False cleanly.
    """
    solver = get_solver()
    if not solver.available:
        return False
    try:
        user_agent = await page.evaluate("() => navigator.userAgent")
        captcha_url = await page.evaluate(_COOKIE_CHALLENGE_URL_JS)

        cookie_or_token = await solver.solve_cookie_challenge(
            challenge_type,
            page_url=url,
            captcha_url=captcha_url,
            user_agent=user_agent,
            proxy=proxy,
        )
        if not cookie_or_token:
            return False

        # AWS WAF returns a token injected into the page; DataDome/Imperva return
        # a cookie string ("name=value; ...") that must be set on the context.
        if challenge_type == "aws_waf":
            await page.evaluate(
                """(tok) => {
                    const el = document.querySelector('[name="awswaf-response"], #awswaf-response');
                    if (el) el.value = tok;
                    window.awsWafCookieDomainList && (window.__awswaf_token = tok);
                }""",
                cookie_or_token,
            )
        else:
            from urllib.parse import urlparse

            name, _, rest = cookie_or_token.partition("=")
            value = rest.split(";")[0] if rest else ""
            if name and value:
                await page.context.add_cookies([{"name": name.strip(), "value": value.strip(), "url": url}])
            else:
                # Solver returned an opaque token — set it under the vendor's cookie name.
                cookie_name = {"datadome": "datadome", "imperva": "visid_incap"}.get(challenge_type)
                if cookie_name:
                    domain = urlparse(url).hostname or ""
                    await page.context.add_cookies([{"name": cookie_name, "value": cookie_or_token, "domain": domain, "path": "/"}])

        try:
            await page.reload(wait_until="domcontentloaded", timeout=20_000)
        except Exception:
            pass
        html = await page.content()
        cleared = challenge_type.replace("_", "") not in html.lower() and "captcha-delivery" not in html.lower()
        logger.info("cookie_challenge_attempted", url=url, type=challenge_type, cleared=cleared)
        return cleared
    except Exception as exc:
        logger.warning("cookie_challenge_solve_failed", url=url, type=challenge_type, error=str(exc))
        return False
