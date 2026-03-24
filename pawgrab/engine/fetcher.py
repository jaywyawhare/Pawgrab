"""Page fetcher: curl_cffi with TLS impersonation, Playwright fallback."""

from __future__ import annotations

import asyncio
import random
from urllib.parse import urlparse

import structlog
from curl_cffi import CurlHttpVersion
from curl_cffi.requests import AsyncSession

from pawgrab.config import settings
from pawgrab.engine.antibot import (
    SAFARI_TARGETS,
    ChallengeDetection,
    detect_challenge,
    fallback_impersonate,
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


_MAX_SESSIONS = 12
_MAX_HOST_TARGETS = 2000
_sessions: dict[str, AsyncSession] = {}
_session_lock = asyncio.Lock()
_host_targets: dict[str, str] = {}
_host_targets_lock = asyncio.Lock()


async def _impersonate_for_host(host: str) -> str:
    """Pin a TLS fingerprint per-host for connection reuse.

    Starts with Safari so the fingerprint matches the Playwright fallback
    path — prevents anti-bot systems from seeing two browser families
    from the same IP when curl escalates to headless.
    """
    async with _host_targets_lock:
        if host not in _host_targets:
            if len(_host_targets) >= _MAX_HOST_TARGETS:
                oldest = next(iter(_host_targets))
                del _host_targets[oldest]
            _host_targets[host] = random.choice(SAFARI_TARGETS)
        return _host_targets[host]


async def _get_session(impersonate: str, proxy: str | None = None) -> AsyncSession:
    """Get or create a persistent AsyncSession for the given impersonate target.

    When a specific proxy is given, a fresh (non-cached) session is returned
    so retry attempts can rotate through different proxies.
    """
    session_kwargs: dict = {
        "impersonate": impersonate,
        "timeout": settings.max_timeout / 1000,
    }
    if settings.http3:
        session_kwargs["http_version"] = CurlHttpVersion.V3ONLY

    if proxy:
        session_kwargs["proxy"] = proxy
        return AsyncSession(**session_kwargs)

    if impersonate not in _sessions:
        async with _session_lock:
            if impersonate not in _sessions:
                if len(_sessions) >= _MAX_SESSIONS:
                    oldest_key = next(iter(_sessions))
                    old = _sessions.pop(oldest_key)
                    try:
                        await old.close()
                    except Exception:
                        pass
                _sessions[impersonate] = AsyncSession(**session_kwargs)
    return _sessions[impersonate]


async def close_sessions():
    """Close all persistent sessions. Called on shutdown."""
    async with _session_lock:
        for session in _sessions.values():
            try:
                await session.close()
            except Exception:
                pass
        _sessions.clear()
    async with _host_targets_lock:
        _host_targets.clear()


class FetchResult:
    __slots__ = (
        "html", "status_code", "url", "used_browser", "challenge",
        "resp_headers", "cookies", "screenshot_bytes", "pdf_bytes",
        "content_bytes", "action_warnings",
        "network_requests", "console_logs", "mhtml_data", "ssl_info",
        "retry_count", "websocket_messages", "trace_path",
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
        retry_count: int = 0,
        websocket_messages: list[dict] | None = None,
        trace_path: str | None = None,
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
        self.retry_count = retry_count
        self.websocket_messages = websocket_messages
        self.trace_path = trace_path


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
    browser_type: str | None = None,
    geolocation: dict[str, float] | None = None,
    text_mode: bool = False,
    scroll_to_bottom: bool = False,
    capture_network: bool = False,
    capture_console: bool = False,
    capture_mhtml: bool = False,
    capture_ssl: bool = False,
    capture_websocket: bool = False,
    session_id: str | None = None,
    enable_trace: bool = False,
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

    proxy_entry = None
    proxy_url: str | None = None
    if proxy_pool is not None:
        proxy_entry = await proxy_pool.get_proxy()
        if proxy_entry is not None:
            proxy_url = proxy_entry.url

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
        capture_websocket=capture_websocket,
        session_id=session_id,
        enable_trace=enable_trace,
    )

    if actions and browser_pool is not None:
        return await _fetch_with_browser(url, actions=actions, **_browser_kwargs)

    needs_browser = (
        capture_screenshot or capture_pdf or text_mode
        or scroll_to_bottom or capture_network or capture_console
        or capture_mhtml or geolocation
    )
    if needs_browser and browser_pool is not None:
        return await _fetch_with_browser(url, **_browser_kwargs)

    if wait_for_js is True and browser_pool is not None:
        return await _fetch_with_browser(url, **_browser_kwargs)

    if headers is None:
        headers = {}
    if "Referer" not in headers and "referer" not in headers:
        ref = random_referer()
        if ref:
            headers["Referer"] = ref

    retries = 0

    host = urlparse(url).netloc
    first_target = settings.impersonate or await _impersonate_for_host(host)
    try:
        result = await _fetch_with_curl(
            url, timeout=timeout, impersonate=first_target,
            headers=headers, cookies=cookies, proxy=proxy_url,
        )
        if proxy_entry is not None:
            proxy_entry.mark_success()
    except Exception as exc:
        if proxy_entry is not None:
            proxy_entry.mark_failure(
                is_timeout=is_proxy_error(exc),
                backoff_seconds=settings.proxy_backoff_seconds,
            )
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
            retries += 1
            # Honor Retry-After header on 429s
            retry_delay = _parse_retry_after(result)
            if retry_delay and retry_delay <= 30:
                await asyncio.sleep(retry_delay)
            else:
                await _backoff(attempt)
            retry_target = fallback_impersonate(prev_target)
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
            except Exception as exc:
                if retry_entry is not None:
                    retry_entry.mark_failure(
                        is_timeout=is_proxy_error(exc),
                        backoff_seconds=settings.proxy_backoff_seconds,
                    )
                raise
            merged_cookies.update(result.cookies)
            challenge = _check_challenge(result)
            if not challenge.detected:
                async with _host_targets_lock:
                    _host_targets[host] = retry_target
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

    if wait_for_js is None and browser_pool is not None and result.content_bytes is None:
        if needs_js_rendering(result.html, url=url):
            logger.info("js_rendering_detected", url=url)
            return await _fetch_with_browser(url, **_browser_kwargs)

    result.retry_count = retries
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
    resp_cookies = {}
    if hasattr(resp, "cookies"):
        for k, v in resp.cookies.items():
            resp_cookies[k] = v

    content_type = resp_headers.get("content-type", resp_headers.get("Content-Type", ""))
    content_bytes: bytes | None = None
    html_text = resp.text
    if is_pdf_content(content_type, str(resp.url)):
        content_bytes = resp.content
        html_text = ""

    return FetchResult(
        html=html_text,
        status_code=resp.status_code,
        url=str(resp.url),
        resp_headers=resp_headers,
        cookies=resp_cookies,
        content_bytes=content_bytes,
    )


def _setup_ws_capture(ws, messages: list[dict]):
    """Attach handlers to capture WebSocket frames."""
    ws_url = ws.url
    def _on_frame_sent(payload):
        messages.append({"direction": "sent", "url": ws_url, "data": str(payload)[:5000]})
    def _on_frame_received(payload):
        messages.append({"direction": "received", "url": ws_url, "data": str(payload)[:5000]})
    ws.on("framesent", _on_frame_sent)
    ws.on("framereceived", _on_frame_received)


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
                        # Pass selector as an argument to avoid JS injection via user-supplied strings
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


_CF_WAIT_MS = 10_000
_CF_SETTLE_MS = 6_000
_CF_MIN_TIMEOUT = 60_000

_PROXY_ERROR_INDICATORS = frozenset({
    "net::err_proxy",
    "net::err_tunnel",
    "connection refused",
    "connection reset",
    "connection timed out",
    "failed to connect",
    "could not resolve proxy",
})


def is_proxy_error(exc: Exception) -> bool:
    """Check if an exception is a proxy-related error."""
    msg = str(exc).lower()
    return any(indicator in msg for indicator in _PROXY_ERROR_INDICATORS)

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
    capture_websocket: bool = False,
    session_id: str | None = None,
    enable_trace: bool = False,
) -> FetchResult:
    """Fetch via Playwright with optional session profile and tracing."""
    if settings.solve_cloudflare and timeout < _CF_MIN_TIMEOUT:
        timeout = _CF_MIN_TIMEOUT

    use_session = (
        session_id
        and settings.browser_session_profiles
        and hasattr(pool, "acquire_session_page")
    )
    if use_session:
        page = await pool.acquire_session_page(session_id)
    else:
        page = await pool.acquire()

    try:
        if proxy_url and hasattr(pool, "replace_with_proxied_page") and not use_session:
            page = await pool.replace_with_proxied_page(page, proxy_url, geolocation=geolocation)
    except Exception:
        if use_session:
            await pool.release_session_page(page)
        else:
            await pool.release(page)
        raise

    tracing = enable_trace or settings.browser_trace_enabled
    if tracing and hasattr(pool, "start_trace"):
        trace_name = session_id or "anon"
        await pool.start_trace(page.context, name=trace_name)

    network_requests: list[dict] = [] if capture_network else None
    console_logs: list[dict] = [] if capture_console else None

    try:
        if headers:
            await page.set_extra_http_headers(headers)

        if cookies:
            cookie_list = [
                {"name": k, "value": v, "url": url}
                for k, v in cookies.items()
            ]
            await page.context.add_cookies(cookie_list)

        if text_mode:
            from pawgrab.engine.browser import _BLOCKED_MEDIA_TYPES
            async def _media_block_handler(route):
                if route.request.resource_type in _BLOCKED_MEDIA_TYPES:
                    return await route.abort()
                return await route.continue_()
            await page.route("**/*", _media_block_handler)

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

        if capture_console:
            page.on("console", lambda msg: console_logs.append({
                "type": msg.type,
                "text": msg.text,
                "location": str(msg.location) if hasattr(msg, "location") else None,
            }))

        websocket_messages: list[dict] = [] if capture_websocket else None
        if capture_websocket:
            page.on("websocket", lambda ws: _setup_ws_capture(ws, websocket_messages))

        response = await page.goto(url, timeout=timeout, wait_until="networkidle")

        action_warnings: list[str] = []
        if actions:
            action_warnings = await _execute_actions(page, actions, timeout)

        if scroll_to_bottom:
            try:
                from pawgrab.engine.browser import _SCROLL_TO_BOTTOM_JS
                await page.evaluate(_SCROLL_TO_BOTTOM_JS)
            except Exception as exc:
                logger.warning("scroll_to_bottom_failed", url=url, error=str(exc))

        try:
            from pawgrab.engine.browser import _OVERLAY_REMOVAL_JS
            await page.evaluate(_OVERLAY_REMOVAL_JS)
        except Exception:
            pass

        try:
            from pawgrab.engine.browser import _SHADOW_DOM_FLATTEN_JS
            await page.evaluate(_SHADOW_DOM_FLATTEN_JS)
        except Exception:
            pass

        try:
            from pawgrab.engine.browser import _IFRAME_INLINE_JS
            await page.evaluate(_IFRAME_INLINE_JS)
        except Exception:
            pass

        html = await page.content()
        status = response.status if response else 200

        resp_headers = {}
        if response:
            resp_headers = {k: v for k, v in response.headers.items()}

        challenge = detect_challenge(status, resp_headers, html)
        if challenge.detected and challenge.challenge_type in (
            "cloudflare_js",
            "cloudflare_interstitial",
        ):
            if settings.solve_cloudflare:
                from pawgrab.engine.browser import solve_cloudflare as _solve_cf

                logger.info("attempting_cf_solve", url=url)
                solved = await _solve_cf(page)
                if solved:
                    html = await page.content()
                    return FetchResult(
                        html=html, status_code=200, url=page.url, used_browser=True,
                        action_warnings=action_warnings,
                        network_requests=network_requests,
                        console_logs=console_logs,
                    )

            # Fallback: passive wait for auto-resolve
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

        if capture_mhtml:
            cdp = None
            try:
                cdp = await page.context.new_cdp_session(page)
                snap = await cdp.send("Page.captureSnapshot", {"format": "mhtml"})
                mhtml_data = snap.get("data", "").encode("utf-8")
            except Exception as exc:
                logger.warning("mhtml_capture_failed", url=url, error=str(exc))
            finally:
                if cdp:
                    try:
                        await cdp.detach()
                    except Exception:
                        pass

        if capture_ssl and response:
            ssl_info = await _capture_ssl_info(page, url)

        trace_path = None
        if tracing and hasattr(pool, "stop_trace"):
            trace_name = session_id or "anon"
            trace_path = await pool.stop_trace(page.context, name=trace_name)

        result = FetchResult(
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
            websocket_messages=websocket_messages,
        )
        if trace_path:
            result.trace_path = trace_path
        return result
    finally:
        if use_session:
            await pool.release_session_page(page)
        else:
            await pool.release(page)


async def _capture_ssl_info(page, url: str) -> dict | None:
    """Capture SSL certificate details via CDP Security domain."""
    cdp = None
    try:
        cdp = await page.context.new_cdp_session(page)
        await cdp.send("Security.enable")
        state = await cdp.send("Security.getSecurityState", {})

        if state and "securityState" in state:
            return {
                "security_state": state.get("securityState"),
                "scheme_is_cryptographic": state.get("schemeIsCryptographic", False),
                "explanations": state.get("explanations", []),
            }
    except Exception:
        pass
    finally:
        if cdp:
            try:
                await cdp.detach()
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

    if result.status_code in (403, 429) and len(result.html.strip()) < _SILENT_BLOCK_MAX_BODY:
        return ChallengeDetection(
            detected=True,
            challenge_type="silent_block",
            detail=f"Silent block detected (HTTP {result.status_code}, body {len(result.html)} chars)",
        )

    h = result.resp_headers
    if h.get("cf-mitigated") == "challenge":
        return ChallengeDetection(
            detected=True,
            challenge_type="cloudflare_mitigated",
            detail="cf-mitigated header indicates challenge",
        )

    return challenge


def _parse_retry_after(result: FetchResult) -> float | None:
    """Parse Retry-After header from 429 responses.

    Handles both integer-seconds and HTTP-date formats (RFC 7231).
    """
    if result.status_code != 429:
        return None
    retry_after = result.resp_headers.get("Retry-After") or result.resp_headers.get("retry-after")
    if not retry_after:
        return None
    try:
        return float(retry_after)
    except ValueError:
        pass
    try:  # HTTP-date format: e.g. "Wed, 21 Oct 2015 07:28:00 GMT"
        import time as _time
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(retry_after)
        delay = dt.timestamp() - _time.time()
        return max(0.0, delay)
    except Exception:
        return None
