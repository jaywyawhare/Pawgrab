"""Tests for browser pool fingerprint evasion."""

from pawgrab.engine.browser import (
    _APPLE_GPU_PROFILES,
    _APPLE_RENDERERS,
    _HARMFUL_DEFAULT_ARGS,
    _LOCALES,
    _STEALTH_CHROMIUM_ARGS,
    _TIMEZONES,
    _VIEWPORTS,
    _build_evasion_script,
    _detect_cloudflare,
    _pick_gpu_profile,
    _strip_section,
)


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
    script = _build_evasion_script()
    assert any(r in script for r in _APPLE_RENDERERS)


def test_build_evasion_script_varies():
    scripts = {_build_evasion_script() for _ in range(20)}
    assert len(scripts) > 1


def test_timezones_and_locales_populated():
    assert len(_TIMEZONES) >= 5
    assert len(_LOCALES) >= 3
    assert all(isinstance(tz, str) for tz in _TIMEZONES)
    assert all(isinstance(loc, str) for loc in _LOCALES)


def test_viewports_have_required_keys():
    for vp in _VIEWPORTS:
        assert "width" in vp
        assert "height" in vp
        assert vp["width"] > 0
        assert vp["height"] > 0


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


def test_gpu_profiles_have_weights():
    for renderer, concurrency, weight in _APPLE_GPU_PROFILES:
        assert isinstance(renderer, str)
        assert concurrency > 0
        assert weight > 0


def test_pick_gpu_profile_returns_consistent_tuple():
    renderer, hw, dev_mem = _pick_gpu_profile()
    assert renderer in _APPLE_RENDERERS
    assert hw in (4, 8, 10, 12)
    assert dev_mem in (4, 8, 16, 32)


def test_pick_gpu_profile_pro_gets_more_memory():
    """Pro/Max GPUs should get 16 or 32 GB device memory."""
    for _ in range(50):
        renderer, hw, dev_mem = _pick_gpu_profile()
        if "Pro" in renderer or "Max" in renderer:
            assert dev_mem in (16, 32)


def test_pick_gpu_profile_varies():
    profiles = {_pick_gpu_profile()[0] for _ in range(100)}
    assert len(profiles) > 2


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
