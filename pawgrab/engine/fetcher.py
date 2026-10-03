"""Page fetcher: curl_cffi with TLS impersonation, Playwright fallback."""

from __future__ import annotations

import asyncio
import random
import re
import time
from urllib.parse import urljoin, urlparse

import structlog
from curl_cffi import CurlHttpVersion
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import DNSError, SSLError

from pawgrab.config import settings
from pawgrab.engine.antibot import (
    ChallengeDetection,
    detect_challenge,
    fallback_impersonate,
    random_referer,
    targets_for_platform,
)
from pawgrab.engine.detector import needs_js_rendering
from pawgrab.engine.pdf_extractor import is_pdf_content
from pawgrab.utils.url_safety import assert_public_url

logger = structlog.get_logger()


_BROWSER_SOLVABLE_CHALLENGES = frozenset(
    {
        "cloudflare_js",
        "cloudflare_managed",
        "cloudflare_turnstile",
        "cloudflare_interstitial",
    }
)

_SOLVER_REQUIRED_CHALLENGES = frozenset({"recaptcha", "hcaptcha"})


_COOKIE_SOLVABLE_CHALLENGES = frozenset({"datadome", "imperva", "aws_waf", "perimeterx", "akamai"})


def _is_browser_solvable(challenge) -> bool:
    if not challenge or not challenge.challenge_type:
        return False
    if challenge.challenge_type in _BROWSER_SOLVABLE_CHALLENGES:
        return True

    if challenge.challenge_type in _SOLVER_REQUIRED_CHALLENGES or challenge.challenge_type in _COOKIE_SOLVABLE_CHALLENGES:
        from pawgrab.engine.captcha_solver import get_solver

        return get_solver().available
    return False


async def _backoff(attempt: int) -> None:
    """Exponential backoff with jitter between retry attempts."""
    if attempt <= 1:
        return
    delay = min(2 ** (attempt - 1) + random.uniform(0, 1), 10.0)
    await asyncio.sleep(delay)


_BLOCKED_HEADERS = frozenset(
    {
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
    }
)


def _sanitize_headers(headers: dict[str, str] | None) -> dict[str, str] | None:
    """Strip dangerous headers that could enable SSRF or request smuggling."""
    if not headers:
        return headers
    return {k: v for k, v in headers.items() if k.lower() not in _BLOCKED_HEADERS}


_MAX_SESSIONS = 12
_MAX_HOST_TARGETS = 2000


_MAX_CAPTURE_ENTRIES = 5000
_sessions: dict[str, AsyncSession] = {}
_session_lock = asyncio.Lock()
_host_targets: dict[str, str] = {}
_host_targets_lock = asyncio.Lock()


async def _impersonate_for_host(host: str) -> str:
    """Pin a TLS fingerprint per-host for connection reuse.
    Starts from the platform identity (Safari by default) so the fingerprint
    matches both the Playwright fallback path and ``fingerprint_platform`` —
    prevents anti-bot systems from seeing two browser families from the same IP
    when curl escalates to headless.
    """
    async with _host_targets_lock:
        if host not in _host_targets:
            if len(_host_targets) >= _MAX_HOST_TARGETS:
                oldest = next(iter(_host_targets))
                del _host_targets[oldest]
            candidates = targets_for_platform(settings.fingerprint_platform)
            _host_targets[host] = random.choice(candidates)
        return _host_targets[host]


async def reset_host_identity(url: str) -> None:
    """Forget the pinned TLS target, warm-up state and cooldown for this URL's
    host so the next attempt draws a fresh impersonate identity instead of
    repeating the one that was just blocked."""
    netloc = urlparse(url).netloc
    async with _host_targets_lock:
        _host_targets.pop(netloc, None)
    _WARMED_HOSTS.pop(netloc, None)
    async with _cooldown_lock:
        _HOST_COOLDOWNS.pop(netloc, None)
        _HOST_BLOCK_STREAKS.pop(netloc, None)


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

    existing = _sessions.get(impersonate)
    if existing is not None:
        return existing
    async with _session_lock:
        existing = _sessions.get(impersonate)
        if existing is not None:
            return existing
        if len(_sessions) >= _MAX_SESSIONS:
            oldest_key = next(iter(_sessions))
            _sessions.pop(oldest_key, None)
        session = AsyncSession(**session_kwargs)
        _sessions[impersonate] = session
        return session


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


_WARMED_HOSTS: dict[str, float] = {}
_WARM_TTL_SECONDS = 900

# Per-host adaptive cooldown: immediately re-hitting a host that just flagged
# us is the fastest route to a permanent ban, so blocks put the host (not the
# request) into a shared cooling-off period.

_RATE_LIMIT_STATUSES = frozenset({429, 503})
_RATE_LIMIT_MAX_RETRIES = 2
_COOLDOWN_BASE_S = 5.0
_COOLDOWN_CAP_S = 120.0
_COOLDOWN_APPLY_CAP_S = 15.0

_HOST_COOLDOWNS: dict[str, float] = {}  # netloc -> monotonic time cooldown ends
_HOST_BLOCK_STREAKS: dict[str, int] = {}  # netloc -> consecutive blocked responses
_cooldown_lock = asyncio.Lock()


async def _penalize_host(host: str, retry_after: float | None = None) -> None:
    """Put a host into cooldown after a blocked response."""
    async with _cooldown_lock:
        streak = _HOST_BLOCK_STREAKS.get(host, 0) + 1
        _HOST_BLOCK_STREAKS[host] = streak
        seconds = min(_COOLDOWN_BASE_S * (2 ** (streak - 1)), _COOLDOWN_CAP_S)
        if retry_after:
            seconds = max(seconds, min(retry_after, _COOLDOWN_CAP_S))
        until = time.monotonic() + seconds
        if until > _HOST_COOLDOWNS.get(host, 0.0):
            _HOST_COOLDOWNS[host] = until


async def _reward_host(host: str) -> None:
    """Clear cooldown state after a clean response."""
    async with _cooldown_lock:
        _HOST_BLOCK_STREAKS.pop(host, None)
        _HOST_COOLDOWNS.pop(host, None)


async def _host_cooldown_remaining(host: str) -> float:
    async with _cooldown_lock:
        return max(0.0, _HOST_COOLDOWNS.get(host, 0.0) - time.monotonic())


async def _warm_session(url: str, impersonate: str, proxy: str | None) -> dict[str, str]:
    """Fetch the origin root before a deep URL so CDN/anti-bot cookies
    (``__cf_bm``, ``__ddg2``, …) already exist — a cold first hit on an article
    URL is a classic bot pattern.  Cached per-host with a TTL; best-effort.
    """
    parsed = urlparse(url)
    if parsed.path in ("", "/"):
        return {}
    now = time.monotonic()
    if now - _WARMED_HOSTS.get(parsed.netloc, 0.0) < _WARM_TTL_SECONDS:
        return {}
    _WARMED_HOSTS[parsed.netloc] = now
    if len(_WARMED_HOSTS) > _MAX_HOST_TARGETS:
        oldest = min(_WARMED_HOSTS, key=_WARMED_HOSTS.get)
        del _WARMED_HOSTS[oldest]
    try:
        session = await _get_session(impersonate, proxy=proxy)
        resp = await session.get(
            f"{parsed.scheme}://{parsed.netloc}/",
            timeout=min(settings.max_timeout / 1000, 10),
            allow_redirects=True,
        )
        cookies = {k: v for k, v in resp.cookies.items()} if hasattr(resp, "cookies") else {}
        if cookies:
            logger.debug("session_warmed", host=parsed.netloc, cookies=len(cookies))
        return cookies
    except Exception as exc:
        logger.debug("session_warm_failed", host=parsed.netloc, error=str(exc))
        return {}


class FetchResult:
    __slots__ = (
        "html",
        "status_code",
        "url",
        "used_browser",
        "challenge",
        "resp_headers",
        "cookies",
        "screenshot_bytes",
        "pdf_bytes",
        "content_bytes",
        "action_warnings",
        "network_requests",
        "console_logs",
        "mhtml_data",
        "ssl_info",
        "retry_count",
        "websocket_messages",
        "trace_path",
        "readability_html",
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
        readability_html: str | None = None,
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
        self.readability_html = readability_html


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
    prefer_premium: bool = False,
) -> FetchResult:
    """Fetch a page via curl_cffi (with TLS impersonation) or Playwright.

    Escalation chain:
      1. Safari TLS fingerprint via curl_cffi  (default, ~70 % of the time)
      2. If challenged → retry with a *different browser family* (switches
         the entire TLS stack — JA3 hash, cipher ordering, HTTP/2 framing)
      3. If still challenged → escalate to headless Playwright

    ``prefer_premium`` selects the residential/mobile proxy tier first instead
    of the standard tier.
    """
    timeout = min(timeout, settings.max_timeout)
    headers = _sanitize_headers(headers)
    proxy_entry = None
    proxy_url: str | None = None
    if proxy_pool is not None:
        proxy_entry = await proxy_pool.get_proxy(premium=True) if prefer_premium else await proxy_pool.get_proxy()
        if proxy_entry is not None:
            proxy_url = proxy_entry.url
    _browser_kwargs = dict(
        timeout=timeout,
        pool=browser_pool,
        headers=headers,
        cookies=cookies,
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
    needs_browser = capture_screenshot or capture_pdf or text_mode or scroll_to_bottom or capture_network or capture_console or capture_mhtml or geolocation
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
    cooldown = await _host_cooldown_remaining(host)
    if cooldown > 0:
        wait = min(cooldown, _COOLDOWN_APPLY_CAP_S)
        logger.info("host_cooldown_wait", url=url, seconds=round(wait, 1))
        await asyncio.sleep(wait)
    if settings.session_warming:
        warm_cookies = await _warm_session(url, first_target, proxy_url)
        if warm_cookies:
            headers = dict(headers or {}) if headers else {}
            cookies = {**warm_cookies, **(cookies or {})}
    dns_retries = 2
    for _dns_attempt in range(1, dns_retries + 2):
        try:
            result = await _fetch_with_curl(
                url,
                timeout=timeout,
                impersonate=first_target,
                headers=headers,
                cookies=cookies,
                proxy=proxy_url,
            )
            if proxy_entry is not None:
                proxy_entry.mark_success()
            break
        except DNSError as exc:
            if proxy_entry is not None:
                proxy_entry.mark_failure(
                    is_timeout=False,
                    backoff_seconds=settings.proxy_backoff_seconds,
                )
            if _dns_attempt > dns_retries:
                raise
            await _backoff(_dns_attempt + 1)
            logger.warning("dns_error_retry", url=url, attempt=_dns_attempt, error=str(exc))
        except Exception as exc:
            if proxy_entry is not None:
                proxy_entry.mark_failure(
                    is_timeout=is_proxy_error(exc),
                    backoff_seconds=settings.proxy_backoff_seconds,
                )
            raise
    challenge = _check_challenge(result)
    if challenge.detected:
        await _penalize_host(host, _parse_retry_after(result))
        logger.warning(
            "challenge_detected",
            url=url,
            type=challenge.challenge_type,
            impersonate=first_target,
            attempt=1,
        )
        prev_target = first_target

        merged_cookies = dict(cookies or {})
        merged_cookies.update(result.cookies)
        for attempt in range(2, settings.max_challenge_retries + 2):
            retries += 1

            retry_delay = _parse_retry_after(result)
            if retry_delay and retry_delay <= 30:
                await asyncio.sleep(retry_delay)
            else:
                await _backoff(attempt)
            retry_target = fallback_impersonate(prev_target)
            retry_entry = None
            retry_proxy: str | None = None
            if proxy_pool is not None:
                retry_entry = await proxy_pool.get_proxy(premium=True) or await proxy_pool.get_proxy()
                if retry_entry is not None:
                    retry_proxy = retry_entry.url
            try:
                result = await _fetch_with_curl(
                    url,
                    timeout=timeout,
                    impersonate=retry_target,
                    headers=headers,
                    cookies=merged_cookies or None,
                    proxy=retry_proxy,
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

        if challenge.detected and browser_pool is not None and _is_browser_solvable(challenge):
            logger.info("escalating_to_browser", url=url, type=challenge.challenge_type)
            browser_proxy_url: str | None = None
            if proxy_pool is not None:
                browser_entry = await proxy_pool.get_proxy(premium=True) or await proxy_pool.get_proxy()
                if browser_entry is not None:
                    browser_proxy_url = browser_entry.url
            _browser_kwargs["proxy_url"] = browser_proxy_url

            _browser_kwargs["cookies"] = merged_cookies or _browser_kwargs.get("cookies")
            return await _fetch_with_browser(url, **_browser_kwargs)
        if challenge.detected:
            result.challenge = challenge
            return result
    else:
        await _reward_host(host)

    # Plain rate-limit response (no challenge page): retry on the same
    # identity, honoring Retry-After.
    while not challenge.detected and result.status_code in _RATE_LIMIT_STATUSES and retries < _RATE_LIMIT_MAX_RETRIES:
        retries += 1
        delay = _parse_retry_after(result)
        if delay is None:
            delay = min(2**retries + random.uniform(0, 1), 20.0)
        logger.warning("rate_limited_retry", url=url, status=result.status_code, delay=round(delay, 1), attempt=retries)
        await asyncio.sleep(min(delay, _COOLDOWN_CAP_S))
        try:
            result = await _fetch_with_curl(
                url,
                timeout=timeout,
                impersonate=first_target,
                headers=headers,
                cookies=cookies,
                proxy=proxy_url,
            )
        except Exception as exc:
            if proxy_entry is not None:
                proxy_entry.mark_failure(
                    is_timeout=is_proxy_error(exc),
                    backoff_seconds=settings.proxy_backoff_seconds,
                )
            raise
        challenge = _check_challenge(result)
        if challenge.detected:
            await _penalize_host(host, _parse_retry_after(result))
            break
    if not challenge.detected:
        await _reward_host(host)
    if wait_for_js is None and browser_pool is not None and result.content_bytes is None:
        if needs_js_rendering(result.html, url=url):
            logger.info("js_rendering_detected", url=url)
            return await _fetch_with_browser(url, **_browser_kwargs)
    result.retry_count = retries
    return result


_REDIRECT_STATUS = (301, 302, 303, 307, 308)


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

    async def _single(target: str, verify: bool):

        return await session.get(
            target,
            timeout=timeout_s,
            allow_redirects=False,
            headers=headers,
            cookies=cookies,
            verify=verify,
        )

    async def _guarded_get(target: str):
        try:
            return await _single(target, True)
        except SSLError as exc:
            if not settings.allow_insecure_ssl:
                logger.warning("curl_ssl_error", url=target, impersonate=impersonate, error=str(exc))
                raise
            logger.warning("curl_ssl_retry_no_verify", url=target, impersonate=impersonate, error=str(exc))
            return await _single(target, False)

    try:
        current = url
        resp = None
        for _hop in range(settings.max_redirects + 1):
            resp = await _guarded_get(current)
            location = resp.headers.get("location") or resp.headers.get("Location")
            if resp.status_code in _REDIRECT_STATUS and location:
                nxt = urljoin(current, location)

                await assert_public_url(nxt)
                current = nxt
                continue
            break
    except Exception as exc:
        logger.warning("curl_fetch_failed", url=url, impersonate=impersonate, error=str(exc))
        raise
    finally:
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
    if is_pdf_content(content_type, str(resp.url)):
        content_bytes = resp.content
        html_text = ""
    else:
        html_text = _decode_body(resp, content_type)
    return FetchResult(
        html=html_text,
        status_code=resp.status_code,
        url=str(resp.url),
        resp_headers=resp_headers,
        cookies=resp_cookies,
        content_bytes=content_bytes,
    )


_CHARSET_RE = re.compile(rb'charset=["\']?\s*([\w\-]+)', re.IGNORECASE)


def _decode_body(resp, content_type: str) -> str:
    """Decode a response body, detecting the charset when the server's is missing/wrong.

    curl_cffi's ``resp.text`` uses the declared charset, which is often absent or
    wrong on long-tail sites, producing mojibake. When the declared encoding is
    missing or a bare fallback, sniff the real one from the bytes (meta charset,
    then charset-normalizer) so downstream extraction sees correct text.
    """
    declared = (resp.encoding or "").lower()

    if declared and declared not in ("iso-8859-1", "ascii", "us-ascii"):
        return resp.text
    body = resp.content
    if not body:
        return resp.text

    m = _CHARSET_RE.search(body[:4096])
    if m:
        enc = m.group(1).decode("ascii", "ignore")
        try:
            return body.decode(enc, errors="replace")
        except (LookupError, ValueError):
            pass
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(body).best()
        if best is not None:
            return str(best)
    except Exception:
        pass
    return resp.text


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


_CF_WAIT_MS = 10_000
_CF_SETTLE_MS = 6_000
_CF_MIN_TIMEOUT = 60_000


_CF_SOLVE_BUDGET_S = 20.0
_PROXY_ERROR_INDICATORS = frozenset(
    {
        "net::err_proxy",
        "net::err_tunnel",
        "connection refused",
        "connection reset",
        "connection timed out",
        "failed to connect",
        "could not resolve proxy",
    }
)


def is_proxy_error(exc: Exception) -> bool:
    """Check if an exception is a proxy-related error."""
    msg = str(exc).lower()
    return any(indicator in msg for indicator in _PROXY_ERROR_INDICATORS)


_READABILITY_JS: str | None = None


def _load_readability_js() -> str:
    global _READABILITY_JS
    if _READABILITY_JS is None:
        import pathlib

        js_path = pathlib.Path(__file__).parent / "readability.js"
        if js_path.exists():
            _READABILITY_JS = js_path.read_text(encoding="utf-8")
        else:
            _READABILITY_JS = ""
    return _READABILITY_JS


async def _run_readability_js(page) -> str | None:
    """Inject Mozilla Readability.js into the page and extract article HTML."""
    try:
        js = _load_readability_js()
        if not js:
            return None
        result = await page.evaluate(f"""
            () => {{
                {js}
                try {{
                    const doc = document.cloneNode(true);
                    const article = new Readability(doc).parse();
                    return article ? article.content : null;
                }} catch(e) {{
                    return null;
                }}
            }}
        """)
        if result and isinstance(result, str) and len(result) > 200:
            return result
    except Exception:
        pass
    return None


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
    use_session = session_id and settings.browser_session_profiles and hasattr(pool, "acquire_session_page")

    use_isolated = bool(cookies) and not use_session and hasattr(pool, "new_isolated_page")
    if use_session:
        page = await pool.acquire_session_page(session_id)
    elif use_isolated:
        page = await pool.new_isolated_page(proxy_url=proxy_url, geolocation=geolocation)
    else:
        page = await pool.acquire()

    async def _release(pg):
        if use_session:
            await pool.release_session_page(pg)
        elif use_isolated:
            await pool.release_isolated_page(pg)
        else:
            await pool.release(pg)

    try:
        if proxy_url and not use_isolated and hasattr(pool, "replace_with_proxied_page") and not use_session:
            page = await pool.replace_with_proxied_page(page, proxy_url, geolocation=geolocation)
    except Exception:
        await _release(page)
        raise
    tracing = enable_trace or settings.browser_trace_enabled
    if tracing and hasattr(pool, "start_trace"):
        trace_name = session_id or "anon"
        await pool.start_trace(page.context, name=trace_name)
    network_requests: list[dict] = [] if capture_network else None
    console_logs: list[dict] = [] if capture_console else None

    _listeners: list[tuple[str, object]] = []
    _routes: list[object] = []
    try:
        if headers:
            await page.set_extra_http_headers(headers)
        if cookies:
            cookie_list = [{"name": k, "value": v, "url": url} for k, v in cookies.items()]
            await page.context.add_cookies(cookie_list)
        if text_mode:
            from pawgrab.engine.browser import _BLOCKED_MEDIA_TYPES

            async def _media_block_handler(route, request=None):
                if route.request.resource_type in _BLOCKED_MEDIA_TYPES:
                    return await route.abort()
                return await route.continue_()

            await page.route("**/*", _media_block_handler)
            _routes.append(_media_block_handler)
        if capture_network:

            def _on_request(req):
                if len(network_requests) >= _MAX_CAPTURE_ENTRIES:
                    return
                network_requests.append(
                    {
                        "url": req.url,
                        "method": req.method,
                        "resource_type": req.resource_type,
                        "headers": dict(req.headers),
                    }
                )

            def _on_response(resp):
                if len(network_requests) >= _MAX_CAPTURE_ENTRIES:
                    return
                network_requests.append({"url": resp.url, "status": resp.status, "headers": dict(resp.headers)})

            page.on("request", _on_request)
            page.on("response", _on_response)
            _listeners.append(("request", _on_request))
            _listeners.append(("response", _on_response))
        if capture_console:

            def _on_console(msg):
                if len(console_logs) >= _MAX_CAPTURE_ENTRIES:
                    return
                console_logs.append(
                    {
                        "type": msg.type,
                        "text": msg.text,
                        "location": str(msg.location) if hasattr(msg, "location") else None,
                    }
                )

            page.on("console", _on_console)
            _listeners.append(("console", _on_console))
        websocket_messages: list[dict] = [] if capture_websocket else None
        if capture_websocket:

            def _on_ws(ws):
                _setup_ws_capture(ws, websocket_messages)

            page.on("websocket", _on_ws)
            _listeners.append(("websocket", _on_ws))
        try:
            response = await page.goto(url, timeout=timeout, wait_until="load")
            try:
                await page.wait_for_load_state("networkidle", timeout=min(timeout // 3, 10_000))
            except Exception:
                pass
        except Exception:
            response = await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        if settings.humanize_interactions and not actions:
            # Deterministic goto→capture timing is a bot signal.
            await asyncio.sleep(random.uniform(0.05, 0.3))
        action_warnings: list[str] = []
        if actions:
            action_warnings = await _execute_actions(page, actions, timeout)
        if scroll_to_bottom:
            try:
                if settings.humanize_interactions:
                    from pawgrab.engine.humanize import human_scroll

                    await human_scroll(page)
                else:
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
            "recaptcha",
            "hcaptcha",
        ):
            from pawgrab.engine.captcha_solver import get_solver, solve_captcha_on_page

            if get_solver().available and await solve_captcha_on_page(page, url, challenge.challenge_type):
                try:
                    await page.wait_for_load_state("networkidle", timeout=_CF_SETTLE_MS)
                except Exception:
                    pass
                html = await page.content()
                if not detect_challenge(status, {}, html).detected:
                    return FetchResult(
                        html=html,
                        status_code=200,
                        url=page.url,
                        used_browser=True,
                        action_warnings=action_warnings,
                        network_requests=network_requests,
                        console_logs=console_logs,
                    )

        if challenge.detected and challenge.challenge_type in _COOKIE_SOLVABLE_CHALLENGES:
            from pawgrab.engine.captcha_solver import get_solver, solve_cookie_challenge_on_page

            if get_solver().available and await solve_cookie_challenge_on_page(page, url, challenge.challenge_type, proxy=proxy_url):
                try:
                    await page.wait_for_load_state("networkidle", timeout=_CF_SETTLE_MS)
                except Exception:
                    pass
                html = await page.content()
                if not detect_challenge(status, {}, html).detected:
                    return FetchResult(
                        html=html,
                        status_code=200,
                        url=page.url,
                        used_browser=True,
                        action_warnings=action_warnings,
                        network_requests=network_requests,
                        console_logs=console_logs,
                    )
        if challenge.detected and challenge.challenge_type in (
            "cloudflare_js",
            "cloudflare_interstitial",
            "cloudflare_managed",
            "cloudflare_turnstile",
        ):
            if settings.solve_cloudflare:
                from pawgrab.engine.browser import solve_cloudflare as _solve_cf

                logger.info("attempting_cf_solve", url=url)

                solved = await _solve_cf(page, max_seconds=_CF_SOLVE_BUDGET_S)

                if not solved:
                    from pawgrab.engine.captcha_solver import (
                        get_solver,
                        solve_captcha_on_page,
                    )

                    if get_solver().available:
                        logger.info("attempting_external_turnstile_solve", url=url)
                        solved = await solve_captcha_on_page(page, url, "turnstile")
                if solved:
                    html = await page.content()
                    return FetchResult(
                        html=html,
                        status_code=200,
                        url=page.url,
                        used_browser=True,
                        action_warnings=action_warnings,
                        network_requests=network_requests,
                        console_logs=console_logs,
                    )

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
                    html=html,
                    status_code=200,
                    url=final_url,
                    used_browser=True,
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

        readability_html = await _run_readability_js(page)
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
            readability_html=readability_html,
        )
        if trace_path:
            result.trace_path = trace_path
        return result
    finally:
        for event, handler in _listeners:
            try:
                page.remove_listener(event, handler)
            except Exception:
                pass
        for handler in _routes:
            try:
                await page.unroute("**/*", handler)
            except Exception:
                pass
        await _release(page)


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


_SILENT_BLOCK_MAX_BODY = 500
_ERROR_PAGE_PATTERNS = [
    re.compile(r"<title[^>]*>\s*(?:502|503|504|500|400|403|404)\b", re.IGNORECASE),
    re.compile(r"\b(?:502|503|504)\s+(?:bad\s+gateway|service\s+unavailable|gateway\s+timeout)\b", re.IGNORECASE),
    re.compile(r"cloudfront.*(?:error|bad\s+gateway)", re.IGNORECASE | re.DOTALL),
    re.compile(r"<title[^>]*>access\s+denied", re.IGNORECASE),
    re.compile(r"request\s+could\s+not\s+be\s+satisfied", re.IGNORECASE),
    re.compile(r"making sure you.re not a bot", re.IGNORECASE),
    re.compile(r"difficulty:\s*\d+.*speed:\s*\d+kH/s", re.IGNORECASE | re.DOTALL),
    re.compile(r"anubis.*calculating\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"<title[^>]*>just a moment", re.IGNORECASE),
    re.compile(r"checking your browser before accessing", re.IGNORECASE),
    re.compile(r"enable javascript and cookies to continue", re.IGNORECASE),
    re.compile(r"please turn javascript on", re.IGNORECASE),
    re.compile(r"^(?:\s*(?:Loading\.\.\.|Try Again|Cancel)\s*)+$", re.MULTILINE),
    re.compile(r"<title[^>]*>loading\.\.\.</title>", re.IGNORECASE),
    re.compile(r"powered and protected by\s*\n?\s*privacy", re.IGNORECASE),
    re.compile(r"<title[^>]*>(?:403 forbidden|forbidden)</title>", re.IGNORECASE),
    re.compile(r"this site is protected by.*bot detection", re.IGNORECASE),
    re.compile(r"<title[^>]*>(?:domain for sale|this domain|buy this domain)", re.IGNORECASE),
    re.compile(r"this domain is for sale", re.IGNORECASE),
]


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

    if result.status_code == 200 and result.html:
        for pattern in _ERROR_PAGE_PATTERNS:
            if pattern.search(result.html[:4000]):
                return ChallengeDetection(
                    detected=True,
                    challenge_type="error_page",
                    detail=f"Error page detected in 200 response (pattern: {pattern.pattern[:40]})",
                )
    return challenge


def _parse_retry_after(result: FetchResult) -> float | None:
    """Parse Retry-After header from 429/503 responses.

    Handles both integer-seconds and HTTP-date formats (RFC 7231).
    """
    if result.status_code not in _RATE_LIMIT_STATUSES:
        return None
    retry_after = result.resp_headers.get("Retry-After") or result.resp_headers.get("retry-after")
    if not retry_after:
        return None
    try:
        return float(retry_after)
    except ValueError:
        pass
    try:
        import time as _time
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(retry_after)
        delay = dt.timestamp() - _time.time()
        return max(0.0, delay)
    except Exception:
        return None
