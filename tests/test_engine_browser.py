"""Tests for browser pool fingerprint evasion."""

from pawgrab.engine.browser import (
    _HARMFUL_DEFAULT_ARGS,
    _STEALTH_CHROMIUM_ARGS,
    _build_evasion_script,
    _detect_cloudflare,
    _strip_section,
)
from pawgrab.engine.fingerprint import build_profile


def test_build_evasion_script_contains_webgl_spoof():
    script = _build_evasion_script()
    assert "UNMASKED_VENDOR_WEBGL" in script
    assert "UNMASKED_RENDERER_WEBGL" in script
    assert "Apple Inc." in script


def test_build_evasion_script_contains_navigator_spoofs():
    script = _build_evasion_script()
    assert "Apple Computer, Inc." in script
    assert "navigator" in script
    assert "vendor" in script
    assert "deviceMemory" in script
    assert "hardwareConcurrency" in script
    assert "maxTouchPoints" in script


def test_build_evasion_script_contains_canvas_noise_firefox():
    """Canvas noise JS is kept for firefox (native flags unavailable)."""
    script = _build_evasion_script(browser_type="firefox")
    assert "getImageData" in script
    assert "noiseR" in script


def test_build_evasion_script_strips_canvas_noise_chromium():
    """Canvas noise JS is stripped on chromium (native flag handles it)."""
    script = _build_evasion_script(browser_type="chromium")
    assert "noiseR" not in script


def test_build_evasion_script_removes_chrome_markers():
    script = _build_evasion_script()
    assert "window.chrome" in script
    assert "webdriver" in script


def test_build_evasion_script_uses_valid_renderer():
    profile = build_profile()
    script = _build_evasion_script(profile=profile)
    assert profile.webgl_renderer in script


def test_build_evasion_script_matches_platform_identity():
    mac = build_profile(platform="macos")
    mac_script = _build_evasion_script(profile=mac)
    assert "MacIntel" in mac_script
    assert "Apple Computer, Inc." in mac_script

    assert "delete window.chrome" in mac_script
    win = build_profile(platform="windows")
    win_script = _build_evasion_script(profile=win)
    assert "Win32" in win_script
    assert "Google Inc." in win_script
    assert win.webgl_renderer in win_script

    assert "delete window.chrome" not in win_script
    assert "Samantha" not in win_script


def test_build_evasion_script_varies():
    scripts = {_build_evasion_script() for _ in range(20)}
    assert len(scripts) > 1


def test_build_evasion_script_has_plugins_spoof():
    script = _build_evasion_script()
    assert "plugins" in script
    assert "PDF Viewer" in script
    assert "mimeTypes" in script


def test_build_evasion_script_has_webrtc_block_firefox():
    """WebRTC block JS is kept for firefox."""
    script = _build_evasion_script(browser_type="firefox")
    assert "RTCPeerConnection" in script
    assert "iceServers" in script


def test_build_evasion_script_strips_webrtc_chromium():
    """WebRTC block JS is stripped on chromium (native flag handles it)."""
    script = _build_evasion_script(browser_type="chromium")
    assert "iceServers" not in script


def test_build_evasion_script_has_audio_context_spoof():
    script = _build_evasion_script()
    assert "AudioContext" in script
    assert "getFloatFrequencyData" in script


def test_build_evasion_script_removes_battery_api():
    script = _build_evasion_script()
    assert "getBattery" in script


def test_build_evasion_script_removes_bluetooth():
    script = _build_evasion_script()
    assert "bluetooth" in script


def test_build_evasion_script_has_speech_synthesis():
    script = _build_evasion_script()
    assert "speechSynthesis" in script


def test_canvas_noise_multi_channel():
    """Canvas noise should modify R, G, B channels independently (firefox)."""
    script = _build_evasion_script(browser_type="firefox")
    assert "noiseR" in script
    assert "noiseG" in script
    assert "noiseB" in script


def test_evasion_script_has_todataurl_noise():
    """toDataURL should also be patched for canvas fingerprinting (firefox)."""
    script = _build_evasion_script(browser_type="firefox")
    assert "toDataURL" in script
    assert "putImageData" in script


def test_stealth_chromium_args_populated():
    assert len(_STEALTH_CHROMIUM_ARGS) >= 80
    assert "--disable-blink-features=AutomationControlled" in _STEALTH_CHROMIUM_ARGS


def test_harmful_default_args_populated():
    assert "--enable-automation" in _HARMFUL_DEFAULT_ARGS
    assert len(_HARMFUL_DEFAULT_ARGS) == 5


def test_stealth_args_include_native_canvas_noise():
    assert "--fingerprinting-canvas-image-data-noise" in _STEALTH_CHROMIUM_ARGS


def test_stealth_args_include_webrtc_policy():
    assert "--webrtc-ip-handling-policy=disable_non_proxied_udp" in _STEALTH_CHROMIUM_ARGS
    assert "--force-webrtc-ip-handling-policy" in _STEALTH_CHROMIUM_ARGS


def test_strip_section_removes_tagged_content():
    text = "before\n// __BEGIN_FOO__\nremoved\n// __END_FOO__\nafter"
    result = _strip_section(text, "FOO")
    assert "removed" not in result
    assert "before" in result
    assert "after" in result


def test_strip_section_no_match():
    text = "unchanged text"
    assert _strip_section(text, "BAR") == text


def test_detect_cloudflare_non_interactive():
    html = "<html><script>cType: 'non-interactive'</script></html>"
    assert _detect_cloudflare(html) == "non-interactive"


def test_detect_cloudflare_managed():
    html = '<html><script>cType: "managed"</script></html>'
    assert _detect_cloudflare(html) == "managed"


def test_detect_cloudflare_interactive():
    html = "<html><script>cType: 'interactive'</script></html>"
    assert _detect_cloudflare(html) == "interactive"


def test_detect_cloudflare_embedded_turnstile():
    html = '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>'
    assert _detect_cloudflare(html) == "embedded_turnstile"


def test_detect_cloudflare_none():
    assert _detect_cloudflare("<html>Normal page</html>") is None
    assert _detect_cloudflare("") is None
    assert _detect_cloudflare(None) is None


def test_stealth_args_include_trust_tokens():
    joined = " ".join(_STEALTH_CHROMIUM_ARGS)
    assert "TrustTokens" in joined


def test_stealth_args_include_async_dns():
    assert "--enable-async-dns" in _STEALTH_CHROMIUM_ARGS


def test_stealth_args_include_tcp_fast_open():
    assert "--enable-tcp-fast-open" in _STEALTH_CHROMIUM_ARGS


def test_stealth_args_include_cookie_encryption_disable():
    assert "--disable-cookie-encryption" in _STEALTH_CHROMIUM_ARGS


def test_stealth_args_include_consolidated_disable_features():
    joined = " ".join(_STEALTH_CHROMIUM_ARGS)
    assert "IsolateOrigins" in joined
    assert "site-per-process" in joined


def test_evasion_script_honors_profile():
    from pawgrab.engine.fingerprint import build_profile

    profile = build_profile(42069)
    script = _build_evasion_script(profile=profile)
    assert profile.webgl_renderer in script
    assert str(profile.hardware_concurrency) in script
    assert str(profile.device_memory) in script


def test_context_kwargs_uses_profile():
    from pawgrab.engine.browser import BrowserPool
    from pawgrab.engine.fingerprint import build_profile

    pool = BrowserPool()
    profile = build_profile(42069)
    kw = pool._context_kwargs(profile=profile)
    assert kw["user_agent"] == profile.user_agent
    assert kw["timezone_id"] == profile.timezone
    assert kw["locale"] == profile.locale
    assert kw["viewport"] == profile.viewport


def test_context_kwargs_geo_overrides_profile():
    from pawgrab.engine.browser import BrowserPool
    from pawgrab.engine.fingerprint import build_profile
    from pawgrab.engine.geoip import ProxyGeo

    pool = BrowserPool()
    profile = build_profile(42069)
    geo = ProxyGeo(
        ip="1.2.3.4",
        timezone="Asia/Tokyo",
        locale="en-US",
        accept_language="en-US,en;q=0.9,ja;q=0.7",
        latitude=35.6,
        longitude=139.7,
        country="JP",
    )
    kw = pool._context_kwargs(proxy_url="http://p:8080", profile=profile, geo=geo)

    assert kw["timezone_id"] == "Asia/Tokyo"
    assert kw["extra_http_headers"]["Accept-Language"] == geo.accept_language

    assert kw["geolocation"]["latitude"] == 35.6
    assert kw["proxy"] == {"server": "http://p:8080"}


async def test_acquire_self_heals_on_timeout(monkeypatch):
    """A starved pool queue mints a page instead of hanging forever (H7)."""
    from unittest.mock import AsyncMock

    from pawgrab.engine.browser import BrowserPool

    pool = BrowserPool()
    sentinel = object()
    pool._mint_page = AsyncMock(return_value=sentinel)

    page = await pool.acquire(timeout=0.05)
    assert page is sentinel
    pool._mint_page.assert_awaited_once()


async def test_release_isolated_page_closes_context():
    from unittest.mock import AsyncMock, MagicMock

    from pawgrab.engine.browser import BrowserPool

    pool = BrowserPool()
    page = MagicMock()
    page.context = MagicMock()
    page.context.close = AsyncMock()
    await pool.release_isolated_page(page)
    page.context.close.assert_awaited_once()


def test_evasion_script_chrome_identity_has_client_hints():
    from pawgrab.engine.fingerprint import build_profile

    win = build_profile(seed=7, platform="windows")
    script = _build_evasion_script(browser_type="chromium", profile=win)
    assert "getHighEntropyValues" in script
    assert 'brand: "Google Chrome"' in script
    import re

    assert not [t for t in re.split(r"__", script) if t.isupper() and t not in ("BEGIN_CHROME_ONLY", "END_CHROME_ONLY")]


def test_evasion_script_safari_identity_drops_user_agent_data():
    from pawgrab.engine.fingerprint import build_profile

    mac = build_profile(seed=7, platform="macos")
    script = _build_evasion_script(browser_type="chromium", profile=mac)
    assert "delete navigator.userAgentData" in script
    assert "getHighEntropyValues" not in script


def test_evasion_script_geometry_and_notification():
    script = _build_evasion_script()
    assert "outerHeight" in script
    assert "availHeight" in script
    assert "Notification, 'permission'" in script.replace("Object.defineProperty(Notification, 'permission'", "Notification, 'permission'")
    assert "requestAdapterInfo" in script


def test_context_kwargs_windows_gets_sec_ch_ua_headers():

    from pawgrab.engine.browser import BrowserPool
    from pawgrab.engine.fingerprint import build_profile

    pool = BrowserPool()
    profile = build_profile(seed=7, platform="windows")
    kwargs = pool._context_kwargs(profile=profile)
    extra = kwargs["extra_http_headers"]
    assert "sec-ch-ua" in extra
    assert "Windows" in extra["sec-ch-ua-platform"]
    assert kwargs["permissions"] == ["geolocation"]


def test_context_kwargs_safari_no_client_hint_headers():
    from pawgrab.engine.browser import BrowserPool
    from pawgrab.engine.fingerprint import build_profile

    pool = BrowserPool()
    profile = build_profile(seed=7, platform="macos")
    kwargs = pool._context_kwargs(profile=profile)
    extra = kwargs["extra_http_headers"]
    assert "sec-ch-ua" not in extra


def test_redact_endpoint_drops_path_and_query():
    from pawgrab.engine.browser import _redact_endpoint

    assert _redact_endpoint("ws://cloak.host:9222/devtools/browser?token=secret") == "ws://cloak.host:9222"
    assert _redact_endpoint("not a url") == "<endpoint>"


def test_cdp_property_chromium_only(monkeypatch):
    from pawgrab.config import settings
    from pawgrab.engine.browser import BrowserPool

    monkeypatch.setattr(settings, "browser_cdp_url", "ws://localhost:9222")
    assert BrowserPool()._cdp is True
    assert BrowserPool(browser_type="firefox")._cdp is False
    monkeypatch.setattr(settings, "browser_cdp_url", "")
    assert BrowserPool()._cdp is False


def test_cdp_url_whitespace_stripped(monkeypatch):
    from pawgrab.config import settings
    from pawgrab.engine.browser import BrowserPool

    monkeypatch.setattr(settings, "browser_cdp_url", "  ws://localhost:9222  ")
    assert BrowserPool()._cdp_url == "ws://localhost:9222"


def _fake_cdp_playwright(monkeypatch):
    """Patch async_playwright so start() connects to a mock CDP browser."""
    from unittest.mock import AsyncMock, MagicMock

    import pawgrab.engine.browser as browser_mod

    ctx = MagicMock()
    ctx.new_page = AsyncMock(side_effect=lambda: MagicMock())
    ctx.add_init_script = AsyncMock()
    ctx.route = AsyncMock()
    ctx.grant_permissions = AsyncMock()
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=ctx)
    browser.close = AsyncMock()
    chromium = MagicMock()
    chromium.connect_over_cdp = AsyncMock(return_value=browser)
    chromium.launch_persistent_context = AsyncMock(side_effect=AssertionError("should not launch"))
    chromium.launch = AsyncMock(side_effect=AssertionError("should not launch"))
    pw = MagicMock()
    pw.chromium = chromium
    pw.stop = AsyncMock()
    starter = MagicMock()
    starter.start = AsyncMock(return_value=pw)
    monkeypatch.setattr(browser_mod, "async_playwright", lambda: starter)
    return browser, ctx, chromium


async def test_start_connects_over_cdp(monkeypatch):
    from pawgrab.config import settings
    from pawgrab.engine.browser import BrowserPool

    monkeypatch.setattr(settings, "browser_cdp_url", "ws://cloak:9222/dt?token=x")
    monkeypatch.setattr(settings, "stealth_mode", False)
    browser, ctx, chromium = _fake_cdp_playwright(monkeypatch)

    pool = BrowserPool(pool_size=2)
    await pool.start()

    chromium.connect_over_cdp.assert_awaited_once()
    assert chromium.connect_over_cdp.await_args.args[0] == "ws://cloak:9222/dt?token=x"
    assert chromium.connect_over_cdp.await_args.kwargs["timeout"] == settings.browser_cdp_timeout_ms
    chromium.launch_persistent_context.assert_not_called()
    assert pool._browser is browser
    assert pool._persistent_ctx is ctx
    assert pool._user_data_dir is None
    assert pool._pages.qsize() == 2

    await pool.stop()
    browser.close.assert_awaited_once()


async def test_cdp_ensure_proxy_browser_reuses_connection(monkeypatch):
    from unittest.mock import MagicMock

    from pawgrab.config import settings
    from pawgrab.engine.browser import BrowserPool

    monkeypatch.setattr(settings, "browser_cdp_url", "ws://cloak:9222")
    browser, _ctx, chromium = _fake_cdp_playwright(monkeypatch)

    pool = BrowserPool()
    pool._playwright = MagicMock(chromium=chromium)
    got = await pool._ensure_proxy_browser()
    assert got is browser
    assert pool._proxy_browser is None
