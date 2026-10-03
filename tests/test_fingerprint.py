"""Tests for deterministic, coherent fingerprint profiles."""

from pawgrab.engine.fingerprint import (
    _APPLE_GPU_PROFILES,
    build_profile,
)


def test_same_seed_is_deterministic():
    assert build_profile(42069) == build_profile(42069)


def test_different_seeds_differ():
    a = build_profile(11111)
    b = build_profile(22222)

    assert a != b


def test_string_seed_is_deterministic():
    assert build_profile("session-abc") == build_profile("session-abc")
    assert build_profile("session-abc") != build_profile("session-xyz")


def test_random_seed_in_cloakbrowser_range():
    for _ in range(20):
        p = build_profile(None)
        assert 10_000 <= p.seed <= 99_999


def test_hardware_matches_gpu_table():
    """hardwareConcurrency must be the value physically tied to the GPU."""
    lookup = {renderer: hw for renderer, hw, _ in _APPLE_GPU_PROFILES}
    for seed in range(100):
        p = build_profile(seed * 7 + 1)
        assert lookup[p.webgl_renderer] == p.hardware_concurrency


def test_timezone_locale_coherent():
    """A London timezone must not advertise en-US as its locale."""
    for seed in range(200):
        p = build_profile(seed * 3 + 1)
        if p.timezone == "Europe/London":
            assert p.locale == "en-GB"
        if p.timezone.startswith("America/"):
            assert p.locale == "en-US"


def test_safari_macos_identity():
    p = build_profile(555)
    assert p.platform == "MacIntel"
    assert p.webgl_vendor == "Apple Inc."
    assert "Safari" in p.user_agent
    assert p.max_touch_points == 0


def test_pro_max_chips_get_more_memory():
    for seed in range(300):
        p = build_profile(seed + 1)
        if "Pro" in p.webgl_renderer or "Max" in p.webgl_renderer:
            assert p.device_memory in (16, 32)


def test_impersonate_target_matches_ua():
    """The TLS target must agree with the advertised browser version."""
    for seed in range(200):
        p = build_profile(seed * 11 + 3)
        if "Safari" in p.user_agent:
            assert p.impersonate_target.startswith("safari")
            version = p.user_agent.split("Version/")[1].split(" ")[0]
            if version.startswith("18.4") or version.startswith("18.3"):
                assert p.impersonate_target == "safari184"
            elif version.startswith("18.0"):
                assert p.impersonate_target == "safari180"
            else:
                assert p.impersonate_target == "safari170"
        else:
            assert p.impersonate_target.startswith("chrome")
            assert "Chrome/" in p.user_agent


def test_windows_chrome_identity():
    p = build_profile(555, platform="windows")
    assert p.platform == "Win32"
    assert p.vendor == "Google Inc."
    assert "Windows NT 10.0" in p.user_agent
    assert "Chrome/" in p.user_agent
    assert p.impersonate_target.startswith("chrome")
    assert p.max_touch_points == 0

    assert "Apple" not in p.webgl_renderer


def test_windows_identity_is_deterministic_and_distinct():
    assert build_profile(42069, platform="windows") == build_profile(42069, platform="windows")
    assert build_profile(42069, platform="windows") != build_profile(42069, platform="macos")


def test_invalid_platform_falls_back_to_setting(monkeypatch):
    from pawgrab.config import settings

    monkeypatch.setattr(settings, "fingerprint_platform", "windows")
    assert build_profile(555, platform="nonsense").platform == "Win32"
    monkeypatch.setattr(settings, "fingerprint_platform", "macos")
    assert build_profile(555).platform == "MacIntel"
