"""Deterministic, coherent browser fingerprint profiles.

CloakBrowser derives an entire fingerprint from a single seed
(``--fingerprint=42069``): the same seed yields the same identity every launch,
and every value (GPU, screen, hardware, timezone, UA) is internally consistent.
That coherence matters more than the individual values — anti-bot systems
cross-check the WebGL renderer against ``hardwareConcurrency``, the viewport
against ``screen``, the timezone against ``Accept-Language``, and flag any
combination that couldn't come from one real machine.

Pawgrab previously picked each of these independently at random per context, so
a session could shift identity between pages and occasionally emit an incoherent
mix.  ``build_profile(seed)`` instead draws every value from one seeded RNG,
locked to a coherent OS/browser identity that also matches the curl_cffi TLS
impersonation target used for plain HTTP fetches (``profile.impersonate_target``
— a Safari UA never pairs with a Chrome JA3, and vice versa).  Passing the same
seed — e.g. derived from a session id — keeps one stable identity across a whole
session.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

PLATFORMS = ("macos", "windows")


_APPLE_GPU_PROFILES = (
    ("Apple M1", 8, 30),
    ("Apple M1 Pro", 10, 15),
    ("Apple M1 Max", 10, 5),
    ("Apple M2", 8, 20),
    ("Apple M2 Pro", 12, 8),
    ("Apple M2 Max", 12, 3),
    ("Apple M3", 8, 10),
    ("Apple M3 Pro", 12, 5),
    ("Intel(R) Iris(TM) Plus Graphics 640", 4, 2),
    ("Intel(R) Iris(TM) Plus Graphics", 4, 2),
)
_WINDOWS_GPU_PROFILES = (
    ("NVIDIA GeForce RTX 4060", 16, 18),
    ("NVIDIA GeForce RTX 4070", 16, 10),
    ("NVIDIA GeForce RTX 3060", 12, 14),
    ("NVIDIA GeForce RTX 2060", 12, 8),
    ("NVIDIA GeForce GTX 1660 SUPER", 12, 6),
    ("AMD Radeon RX 7600", 16, 5),
    ("Intel(R) UHD Graphics 770", 8, 12),
    ("Intel(R) Iris(R) Xe Graphics", 8, 10),
    ("NVIDIA GeForce RTX 3050", 8, 6),
)
_VIEWPORTS = (
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1366, "height": 768},
    {"width": 2560, "height": 1440},
)
_WIN_VIEWPORTS = (
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 1366, "height": 768},
    {"width": 2560, "height": 1440},
    {"width": 1600, "height": 900},
)


_TZ_LOCALE = (
    ("America/New_York", "en-US", "en-US,en;q=0.9"),
    ("America/Chicago", "en-US", "en-US,en;q=0.9"),
    ("America/Denver", "en-US", "en-US,en;q=0.9"),
    ("America/Los_Angeles", "en-US", "en-US,en;q=0.9"),
    ("Europe/London", "en-GB", "en-GB,en;q=0.9"),
    ("Europe/Berlin", "en-GB", "en-GB,en;q=0.9,de;q=0.7"),
    ("Europe/Paris", "en-GB", "en-GB,en;q=0.9,fr;q=0.7"),
)


_SAFARI_VERSIONS = (
    ("17.5", "safari170"),
    ("17.6", "safari170"),
    ("18.0", "safari180"),
    ("18.3", "safari184"),
    ("18.4", "safari184"),
)
_SAFARI_UA_TEMPLATE = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/{webkit} (KHTML, like Gecko) Version/{version} Safari/{webkit}"
_CHROME_VERSIONS = (
    ("136.0.0.0", "chrome136"),
    ("131.0.0.0", "chrome131"),
)
_CHROME_UA_TEMPLATE = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.36"
_SEED_MIN = 10_000
_SEED_MAX = 99_999


@dataclass(frozen=True, slots=True)
class FingerprintProfile:
    """A coherent, reproducible browser identity derived from one seed."""

    seed: int
    user_agent: str
    platform: str
    vendor: str
    webgl_vendor: str
    webgl_renderer: str
    hardware_concurrency: int
    device_memory: int
    viewport: dict
    timezone: str
    locale: str
    accept_language: str
    max_touch_points: int

    impersonate_target: str


def _seed_from(value) -> int:
    """Coerce an arbitrary seed value (int/str/None) into an int in range."""
    if isinstance(value, int) and value:
        return value
    if isinstance(value, str) and value:
        return abs(hash(value)) % (_SEED_MAX - _SEED_MIN) + _SEED_MIN
    return 0


def _resolve_platform(platform: str | None) -> str:
    if platform in PLATFORMS:
        return platform
    from pawgrab.config import settings

    return settings.fingerprint_platform if settings.fingerprint_platform in PLATFORMS else "macos"


def build_profile(seed=None, platform: str | None = None) -> FingerprintProfile:
    """Build a coherent fingerprint profile.

    ``seed`` may be an int, a string (e.g. a session id, hashed deterministically),
    or ``None``/``0`` for a fresh random identity.  A non-zero seed always yields
    the same profile, so a session can keep one stable identity across pages.

    ``platform`` selects the OS identity ("macos" → Safari, "windows" → Chrome);
    defaults to ``settings.fingerprint_platform``.
    """
    resolved = _seed_from(seed)
    if not resolved:
        resolved = random.randint(_SEED_MIN, _SEED_MAX)
    rng = random.Random(resolved)
    os_platform = _resolve_platform(platform)
    if os_platform == "windows":
        renderers, concurrencies, weights = zip(*_WINDOWS_GPU_PROFILES, strict=True)
        renderer = rng.choices(renderers, weights=weights, k=1)[0]
        idx = renderers.index(renderer)
        hw = concurrencies[idx]
        if "RTX" in renderer or "Radeon" in renderer:
            device_memory = rng.choice((8, 16))
        else:
            device_memory = rng.choice((8, 16, 32))
        viewport = dict(rng.choice(_WIN_VIEWPORTS))
        version, impersonate_target = rng.choice(_CHROME_VERSIONS)
        user_agent = _CHROME_UA_TEMPLATE.format(version=version)
        platform_str, vendor = "Win32", "Google Inc."
        webgl_vendor = "Google Inc. (NVIDIA)"
    else:
        renderers, concurrencies, weights = zip(*_APPLE_GPU_PROFILES, strict=True)
        renderer = rng.choices(renderers, weights=weights, k=1)[0]
        idx = renderers.index(renderer)
        hw = concurrencies[idx]
        if "Pro" in renderer or "Max" in renderer:
            device_memory = rng.choice((16, 32))
        elif "Intel" in renderer:
            device_memory = rng.choice((4, 8))
        else:
            device_memory = 8
        viewport = dict(rng.choice(_VIEWPORTS))
        version, impersonate_target = rng.choice(_SAFARI_VERSIONS)
        user_agent = _SAFARI_UA_TEMPLATE.format(version=version, webkit="605.1.15")
        platform_str, vendor = "MacIntel", "Apple Computer, Inc."
        webgl_vendor = "Apple Inc."
    timezone, locale, accept_language = rng.choice(_TZ_LOCALE)
    return FingerprintProfile(
        seed=resolved,
        user_agent=user_agent,
        platform=platform_str,
        vendor=vendor,
        webgl_vendor=webgl_vendor,
        webgl_renderer=renderer,
        hardware_concurrency=hw,
        device_memory=device_memory,
        viewport=viewport,
        timezone=timezone,
        locale=locale,
        accept_language=accept_language,
        max_touch_points=0,
        impersonate_target=impersonate_target,
    )


__all__ = ["FingerprintProfile", "PLATFORMS", "build_profile"]
