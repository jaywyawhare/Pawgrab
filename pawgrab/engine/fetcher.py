"""Page fetcher: curl_cffi with TLS impersonation, Playwright fallback."""

from __future__ import annotations

import asyncio
import random

import structlog
from curl_cffi.requests import AsyncSession

from pawgrab.config import settings
from pawgrab.engine.antibot import (
    ChallengeDetection,
    detect_challenge,
    fallback_impersonate,
    random_impersonate,
    random_referer,
)
from pawgrab.engine.detector import needs_js_rendering
from pawgrab.engine.pdf_extractor import is_pdf_content

logger = structlog.get_logger()

async def _backoff(attempt: int) -> None:
    """Exponential backoff with jitter between retry attempts."""
    if attempt <= 1:
        return
    delay = min(2 ** (attempt - 1) + random.uniform(0, 1), 10.0)
    await asyncio.sleep(delay)

_BLOCKED_HEADERS = frozenset({
    "host",
    "content-length",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "expect",
    "te",
    "trailer",
    "upgrade",
    "proxy-authorization",
    "proxy-connection",
})


def _sanitize_headers(headers: dict[str, str] | None) -> dict[str, str] | None:
    """Strip dangerous headers that could enable SSRF or request smuggling."""
    if not headers:
        return headers
    return {k: v for k, v in headers.items() if k.lower() not in _BLOCKED_HEADERS}


_MAX_SESSIONS = 12  # cap session pool size
_sessions: dict[str, AsyncSession] = {}
_session_lock = asyncio.Lock()


async def _get_session(impersonate: str, proxy: str | None = None) -> AsyncSession:
    """Get or create a persistent AsyncSession for the given impersonate target.

    When a specific proxy is given, a fresh (non-cached) session is returned
    so retry attempts can rotate through different proxies.
    """
    # Proxy-specific sessions are not cached (they change per retry)
    if proxy:
        return AsyncSession(
            impersonate=impersonate,
            proxy=proxy,
            timeout=settings.max_timeout / 1000,
        )

    if impersonate not in _sessions:
        async with _session_lock:
            if impersonate not in _sessions:
                # Evict oldest session if at capacity
                if len(_sessions) >= _MAX_SESSIONS:
                    oldest_key = next(iter(_sessions))
                    old = _sessions.pop(oldest_key)
                    try:
                        await old.close()
                    except Exception:
                        pass
                _sessions[impersonate] = AsyncSession(
                    impersonate=impersonate,
                    timeout=settings.max_timeout / 1000,
                )
    return _sessions[impersonate]


async def close_sessions():
    """Close all persistent sessions. Called on shutdown."""
    for session in _sessions.values():
        try:
            await session.close()
        except Exception:
            pass
    _sessions.clear()


class FetchResult:
    __slots__ = (
        "html", "status_code", "url", "used_browser", "challenge",
        "resp_headers", "cookies", "screenshot_bytes", "pdf_bytes",
        "content_bytes", "action_warnings",
        "network_requests", "console_logs", "mhtml_data", "ssl_info",
    )

    def __init__(
        self,
        html: str,
        status_code: int,
        url: str,
        *,
        used_browser: bool = False,
        challenge: ChallengeDetection | None = None,
        resp_headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        screenshot_bytes: bytes | None = None,
        pdf_bytes: bytes | None = None,
        content_bytes: bytes | None = None,
        action_warnings: list[str] | None = None,
        network_requests: list[dict] | None = None,
        console_logs: list[dict] | None = None,
        mhtml_data: bytes | None = None,
        ssl_info: dict | None = None,
    ):
        self.html = html
        self.status_code = status_code
        self.url = url
        self.used_browser = used_browser
        self.challenge = challenge
        self.resp_headers = resp_headers or {}
        self.cookies = cookies or {}
        self.screenshot_bytes = screenshot_bytes
        self.pdf_bytes = pdf_bytes
        self.content_bytes = content_bytes
        self.action_warnings = action_warnings or []
        self.network_requests = network_requests
        self.console_logs = console_logs
        self.mhtml_data = mhtml_data
        self.ssl_info = ssl_info


async def fetch_page(
    url: str,
    *,
    wait_for_js: bool | None = None,
    timeout: int = 30_000,
    browser_pool: object | None = None,
    proxy_pool: object | None = None,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    capture_screenshot: bool = False,
    screenshot_fullpage: bool = True,
    capture_pdf: bool = False,
    actions: list | None = None,
    # Browser enhancements
    browser_type: str | None = None,
    geolocation: dict[str, float] | None = None,
    text_mode: bool = False,
    scroll_to_bottom: bool = False,
    # Capture options
    capture_network: bool = False,
    capture_console: bool = False,
    capture_mhtml: bool = False,
    capture_ssl: bool = False,
) -> FetchResult:
    """Fetch a page via curl_cffi (with TLS impersonation) or Playwright.

    Escalation chain:
      1. Safari TLS fingerprint via curl_cffi  (default, ~70 % of the time)
      2. If challenged → retry with a *different browser family* (switches
         the entire TLS stack — JA3 hash, cipher ordering, HTTP/2 framing)
      3. If still challenged → escalate to headless Playwright
    """
    timeout = min(timeout, settings.max_timeout)
    headers = _sanitize_headers(headers)

    # Get proxy from pool for this request
    proxy_entry = None
    proxy_url: str | None = None
    if proxy_pool is not None:
        proxy_entry = await proxy_pool.get_proxy()
        if proxy_entry is not None:
            proxy_url = proxy_entry.url

    # Common kwargs for _fetch_with_browser
    _browser_kwargs = dict(
        timeout=timeout, pool=browser_pool,
        headers=headers, cookies=cookies,
        capture_screenshot=capture_screenshot,
        screenshot_fullpage=screenshot_fullpage,
        capture_pdf=capture_pdf,
        proxy_url=proxy_url,
        geolocation=geolocation,
        text_mode=text_mode,
        scroll_to_bottom=scroll_to_bottom,
        capture_network=capture_network,
        capture_console=capture_console,
        capture_mhtml=capture_mhtml,
        capture_ssl=capture_ssl,
    )

    # Force browser when actions are present
    if actions and browser_pool is not None:
        return await _fetch_with_browser(url, actions=actions, **_browser_kwargs)

    # Force browser when captures requested
    needs_browser = (
        capture_screenshot or capture_pdf or text_mode
        or scroll_to_bottom or capture_network or capture_console
        or capture_mhtml or geolocation
    )
    if needs_browser and browser_pool is not None:
        return await _fetch_with_browser(url, **_browser_kwargs)

    # Go straight to browser when explicitly asked
    if wait_for_js is True and browser_pool is not None:
        return await _fetch_with_browser(url, **_browser_kwargs)

    # Inject a realistic Referer header if none provided
    if headers is None:
        headers = {}
    if "Referer" not in headers and "referer" not in headers:
        ref = random_referer()
        if ref:
            headers["Referer"] = ref

    first_target = settings.impersonate or random_impersonate()
    try:
        result = await _fetch_with_curl(
            url, timeout=timeout, impersonate=first_target,
            headers=headers, cookies=cookies, proxy=proxy_url,
        )
        if proxy_entry is not None:
            proxy_entry.mark_success()
    except Exception:
        if proxy_entry is not None:
            is_timeout = True  # network errors on curl are usually timeouts
            proxy_entry.mark_failure(is_timeout=is_timeout, backoff_seconds=settings.proxy_backoff_seconds)
        raise

    challenge = _check_challenge(result)
    if challenge.detected:
        logger.warning(
            "challenge_detected",
            url=url,
            type=challenge.challenge_type,
            impersonate=first_target,
            attempt=1,
        )

        prev_target = first_target
        # Carry forward cookies from first attempt (anti-bot cookie challenges)
        merged_cookies = dict(cookies or {})
        merged_cookies.update(result.cookies)
        for attempt in range(2, settings.max_challenge_retries + 2):
            # Honor Retry-After header on 429s
            retry_delay = _parse_retry_after(result)
            if retry_delay and retry_delay <= 30:
                await asyncio.sleep(retry_delay)
            else:
                await _backoff(attempt)
            retry_target = fallback_impersonate(prev_target)
            # Get a fresh proxy for each retry
            retry_entry = None
            retry_proxy: str | None = None
            if proxy_pool is not None:
                retry_entry = await proxy_pool.get_proxy()
                if retry_entry is not None:
                    retry_proxy = retry_entry.url
            try:
                result = await _fetch_with_curl(
                    url, timeout=timeout, impersonate=retry_target,
                    headers=headers, cookies=merged_cookies or None, proxy=retry_proxy,
                )
                if retry_entry is not None:
                    retry_entry.mark_success()
            except Exception:
                if retry_entry is not None:
                    retry_entry.mark_failure(is_timeout=True, backoff_seconds=settings.proxy_backoff_seconds)
                raise
            # Accumulate cookies from each response
            merged_cookies.update(result.cookies)
            challenge = _check_challenge(result)
            if not challenge.detected:
                logger.info(
                    "challenge_bypassed",
                    url=url,
                    impersonate=retry_target,
                    attempt=attempt,
                )
                break
            logger.warning(
                "challenge_detected",
                url=url,
                type=challenge.challenge_type,
                impersonate=retry_target,
                attempt=attempt,
            )
            prev_target = retry_target

        if challenge.detected and browser_pool is not None:
            logger.info("escalating_to_browser", url=url)
            browser_proxy_url: str | None = None
            if proxy_pool is not None:
                browser_entry = await proxy_pool.get_proxy()
                if browser_entry is not None:
                    browser_proxy_url = browser_entry.url
            _browser_kwargs["proxy_url"] = browser_proxy_url
            return await _fetch_with_browser(url, **_browser_kwargs)

        if challenge.detected:
            result.challenge = challenge
            return result

    # Auto-detect: check if JS rendering is needed (skip for PDF responses)
    if wait_for_js is None and browser_pool is not None and result.content_bytes is None:
        if needs_js_rendering(result.html, url=url):
            logger.info("js_rendering_detected", url=url)
            return await _fetch_with_browser(url, **_browser_kwargs)

    return result


async def _fetch_with_curl(
    url: str,
    *,
    timeout: int = 30_000,
    impersonate: str = "safari184",
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    proxy: str | None = None,
) -> FetchResult:
    """Fetch a page using curl_cffi with browser TLS impersonation.

    Uses a persistent session per impersonate target for connection reuse.
    When proxy is specified, creates a fresh session for that proxy.
    """
    timeout_s = timeout / 1000
    session = await _get_session(impersonate, proxy=proxy)
    try:
        resp = await session.get(
            url,
            timeout=timeout_s,
            allow_redirects=True,
            headers=headers,
            cookies=cookies,
        )
    except Exception as exc:
        logger.warning("curl_fetch_failed", url=url, impersonate=impersonate, error=str(exc))
        raise
    finally:
        # Close non-cached proxy sessions to prevent leaks
        if proxy:
            try:
                await session.close()
            except Exception:
                pass
    resp_headers = {k: v for k, v in resp.headers.items()}
    # Extract cookies from response for session persistence
    resp_cookies = {}
    if hasattr(resp, "cookies"):
        for k, v in resp.cookies.items():
            resp_cookies[k] = v

    # Detect PDF responses — store raw bytes for extraction in scrape_service
    content_type = resp_headers.get("content-type", resp_headers.get("Content-Type", ""))
    content_bytes: bytes | None = None
    html_text = resp.text
    if is_pdf_content(content_type, str(resp.url)):
        content_bytes = resp.content
        html_text = ""  # no HTML to parse for PDFs

    return FetchResult(
        html=html_text,
        status_code=resp.status_code,
        url=str(resp.url),
        resp_headers=resp_headers,
        cookies=resp_cookies,
        content_bytes=content_bytes,
    )


async def _execute_actions(page: object, actions: list, timeout: int) -> list[str]:
    """Execute page actions sequentially, returning any warnings."""
    from pawgrab.models.scrape import ActionType

    warnings: list[str] = []
    per_action_timeout = max(timeout // (len(actions) + 1), 5_000)

    for i, action in enumerate(actions):
        try:
            match action.type:
                case ActionType.CLICK:
                    await page.click(action.selector, timeout=per_action_timeout)
                case ActionType.TYPE:
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
                    await page.screenshot()
                case ActionType.EXECUTE_JS:
                    await page.evaluate(action.text)
        except Exception as exc:
            msg = f"Action {i} ({action.type.value}) failed: {exc}"
            logger.warning("action_failed", action=action.type.value, index=i, error=str(exc))
            warnings.append(msg)

    return warnings


_CF_WAIT_MS = 10_000  # max time to wait for Cloudflare auto-resolve
_CF_SETTLE_MS = 6_000  # max time to wait for network-idle after redirect

async def _fetch_with_browser(
    url: str,
    *,
    timeout: int = 30_000,
    pool: object,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    capture_screenshot: bool = False,
    screenshot_fullpage: bool = True,
    capture_pdf: bool = False,
    proxy_url: str | None = None,
    actions: list | None = None,
    geolocation: dict[str, float] | None = None,
    text_mode: bool = False,
    scroll_to_bottom: bool = False,
    capture_network: bool = False,
    capture_console: bool = False,
    capture_mhtml: bool = False,
    capture_ssl: bool = False,
) -> FetchResult:
    """Fetch a page using the Playwright browser pool.

    Waits for network-idle, then checks for challenges.  If a Cloudflare
    interstitial is detected, waits for it to auto-resolve.

    Supports: shadow DOM flattening, iframe inlining, overlay removal,
    text-only mode, infinite scroll, network/console capture, MHTML snapshots.
    """
    page = await pool.acquire()
    if proxy_url and hasattr(pool, "replace_with_proxied_page"):
        page = await pool.replace_with_proxied_page(page, proxy_url, geolocation=geolocation)

    # Network request capture
    network_requests: list[dict] = [] if capture_network else None
    console_logs: list[dict] = [] if capture_console else None

    try:
        # Apply custom headers
        if headers:
            await page.set_extra_http_headers(headers)

        # Apply custom cookies
        if cookies:
            cookie_list = [
                {"name": k, "value": v, "url": url}
                for k, v in cookies.items()
            ]
            await page.context.add_cookies(cookie_list)

        # Text-only mode: block images, CSS, fonts for faster loading
        if text_mode:
            await page.route("**/*", _text_mode_route_handler)

        # Set up network request capture
        if capture_network:
            page.on("request", lambda req: network_requests.append({
                "url": req.url,
                "method": req.method,
                "resource_type": req.resource_type,
                "headers": dict(req.headers),
            }))
            page.on("response", lambda resp: network_requests.append({
                "url": resp.url,
                "status": resp.status,
                "headers": dict(resp.headers),
            }))

        # Set up console log capture
        if capture_console:
            page.on("console", lambda msg: console_logs.append({
                "type": msg.type,
                "text": msg.text,
                "location": str(msg.location) if hasattr(msg, "location") else None,
            }))

        response = await page.goto(url, timeout=timeout, wait_until="networkidle")

        # Execute page actions before extracting content
        action_warnings: list[str] = []
        if actions:
            action_warnings = await _execute_actions(page, actions, timeout)

        # Auto-scroll to trigger lazy loading
        if scroll_to_bottom:
            try:
                from pawgrab.engine.browser import _SCROLL_TO_BOTTOM_JS
                await page.evaluate(_SCROLL_TO_BOTTOM_JS)
            except Exception as exc:
                logger.warning("scroll_to_bottom_failed", url=url, error=str(exc))

        # Remove overlays/popups
        try:
            from pawgrab.engine.browser import _OVERLAY_REMOVAL_JS
            await page.evaluate(_OVERLAY_REMOVAL_JS)
        except Exception:
            pass

        # Flatten shadow DOM
        try:
            from pawgrab.engine.browser import _SHADOW_DOM_FLATTEN_JS
            await page.evaluate(_SHADOW_DOM_FLATTEN_JS)
        except Exception:
            pass

        # Inline iframes
        try:
            from pawgrab.engine.browser import _IFRAME_INLINE_JS
            await page.evaluate(_IFRAME_INLINE_JS)
        except Exception:
            pass

        html = await page.content()
        status = response.status if response else 200

        # Extract response headers from Playwright
        resp_headers = {}
        if response:
            resp_headers = {k: v for k, v in response.headers.items()}

        challenge = detect_challenge(status, resp_headers, html)
        if challenge.detected and challenge.challenge_type in (
            "cloudflare_js",
            "cloudflare_interstitial",
        ):
            remaining = max(timeout - 5_000, 2_000)
            cf_wait = min(_CF_WAIT_MS, remaining)
            cf_settle = min(_CF_SETTLE_MS, remaining // 2)

            logger.info("waiting_for_cloudflare", url=url, cf_wait_ms=cf_wait)
            try:
                await page.wait_for_url(
                    lambda u: u != page.url,
                    timeout=cf_wait,
                )
                await page.wait_for_load_state("networkidle", timeout=cf_settle)
            except Exception:
                pass
            html = await page.content()
            final_url = page.url
            challenge = detect_challenge(status, resp_headers, html)
            if not challenge.detected:
                return FetchResult(
                    html=html, status_code=200, url=final_url, used_browser=True,
                    action_warnings=action_warnings,
                    network_requests=network_requests,
                    console_logs=console_logs,
                )

        # Capture screenshot/PDF before releasing the page
        screenshot_bytes = None
        pdf_bytes = None
        mhtml_data = None
        ssl_info = None

        if capture_screenshot:
            try:
                screenshot_bytes = await page.screenshot(full_page=screenshot_fullpage)
            except Exception as exc:
                logger.warning("screenshot_failed", url=url, error=str(exc))
        if capture_pdf:
            try:
                pdf_bytes = await page.pdf()
            except Exception as exc:
                logger.warning("pdf_capture_failed", url=url, error=str(exc))

        # MHTML snapshot via CDP
        if capture_mhtml:
            try:
                cdp = await page.context.new_cdp_session(page)
                result = await cdp.send("Page.captureSnapshot", {"format": "mhtml"})
                mhtml_data = result.get("data", "").encode("utf-8")
                await cdp.detach()
            except Exception as exc:
                logger.warning("mhtml_capture_failed", url=url, error=str(exc))

        # SSL certificate info
        if capture_ssl and response:
            ssl_info = await _capture_ssl_info(page, url)

        return FetchResult(
            html=html,
            status_code=status,
            url=page.url,
            used_browser=True,
            challenge=challenge if challenge.detected else None,
            resp_headers=resp_headers,
            screenshot_bytes=screenshot_bytes,
            pdf_bytes=pdf_bytes,
            action_warnings=action_warnings,
            network_requests=network_requests,
            console_logs=console_logs,
            mhtml_data=mhtml_data,
            ssl_info=ssl_info,
        )
    finally:
        await pool.release(page)


async def _text_mode_route_handler(route):
    """Block non-essential resources for text-only mode."""
    blocked = {"image", "stylesheet", "font", "media"}
    if route.request.resource_type in blocked:
        await route.abort()
    else:
        await route.continue_()


async def _capture_ssl_info(page, url: str) -> dict | None:
    """Capture SSL certificate details via CDP Security domain."""
    try:
        cdp = await page.context.new_cdp_session(page)
        await cdp.send("Security.enable")
        # Get security state which includes certificate info
        state = await cdp.send("Security.getSecurityState", {})
        await cdp.detach()

        if state and "securityState" in state:
            return {
                "security_state": state.get("securityState"),
                "scheme_is_cryptographic": state.get("schemeIsCryptographic", False),
                "explanations": state.get("explanations", []),
            }
    except Exception:
        pass
    return None


_SILENT_BLOCK_MAX_BODY = 500  # 403/429 with body < 500 chars = likely silent block


def _check_challenge(result: FetchResult) -> ChallengeDetection:
    """Run challenge detection against a FetchResult.

    Also detects silent blocks: 403/429 with minimal body content,
    which modern anti-bot systems use instead of visible challenge pages.
    """
    challenge = detect_challenge(result.status_code, result.resp_headers, result.html)
    if challenge.detected:
        return challenge

    # Silent block detection: tiny body on 403/429 with no visible challenge
    if result.status_code in (403, 429) and len(result.html.strip()) < _SILENT_BLOCK_MAX_BODY:
        return ChallengeDetection(
            detected=True,
            challenge_type="silent_block",
            detail=f"Silent block detected (HTTP {result.status_code}, body {len(result.html)} chars)",
        )

    # Header-based detection: anti-bot systems send specific headers
    h = result.resp_headers
    if h.get("cf-mitigated") == "challenge":
        return ChallengeDetection(
            detected=True,
            challenge_type="cloudflare_mitigated",
            detail="cf-mitigated header indicates challenge",
        )

    return challenge


def _parse_retry_after(result: FetchResult) -> float | None:
    """Parse Retry-After header from 429 responses."""
    if result.status_code != 429:
        return None
    retry_after = result.resp_headers.get("Retry-After") or result.resp_headers.get("retry-after")
    if not retry_after:
        return None
    try:
        return float(retry_after)
    except ValueError:
        return None
