"""Tests for browser pool fingerprint evasion."""

from pawgrab.engine.browser import (
    _APPLE_GPU_PROFILES,
    _APPLE_RENDERERS,
    _LOCALES,
    _TIMEZONES,
    _VIEWPORTS,
    _build_evasion_script,
    _pick_gpu_profile,
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


def test_build_evasion_script_contains_canvas_noise():
    script = _build_evasion_script()
    assert "getImageData" in script
    assert "noiseR" in script


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


def test_build_evasion_script_has_webrtc_block():
    script = _build_evasion_script()
    assert "RTCPeerConnection" in script
    assert "iceServers" in script


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
    """Canvas noise should modify R, G, B channels independently."""
    script = _build_evasion_script()
    assert "noiseR" in script
    assert "noiseG" in script
    assert "noiseB" in script


def test_evasion_script_has_todataurl_noise():
    """toDataURL should also be patched for canvas fingerprinting."""
    script = _build_evasion_script()
    assert "toDataURL" in script
    assert "putImageData" in script
