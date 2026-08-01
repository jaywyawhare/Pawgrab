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
locked to a coherent Safari/macOS identity (which matches the curl_cffi Safari
TLS fingerprint and the Safari user-agent used elsewhere).  Passing the same
seed — e.g. derived from a session id — keeps one stable identity across a whole
session.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

# (renderer, hardware_concurrency, weight) — Apple Silicon + a couple of Intel
# Macs, weighted toward the common configs. hw concurrency is tied to the chip so
# the pair is always physically consistent.
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

_VIEWPORTS = (
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1366, "height": 768},
    {"width": 2560, "height": 1440},
)

# Timezone -> (locale, accept-language) kept coherent: a browser reporting
# Europe/London should not advertise en-US as its primary language.
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
    ("17.5", "605.1.15"),
    ("17.6", "605.1.15"),
    ("18.0", "605.1.15"),
    ("18.3", "605.1.15"),
    ("18.4", "605.1.15"),
)
_SAFARI_UA_TEMPLATE = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/{webkit} " "(KHTML, like Gecko) Version/{version} Safari/{webkit}"

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


def _seed_from(value) -> int:
    """Coerce an arbitrary seed value (int/str/None) into an int in range."""
    if isinstance(value, int) and value:
        return value
    if isinstance(value, str) and value:
        return abs(hash(value)) % (_SEED_MAX - _SEED_MIN) + _SEED_MIN
    return 0


def build_profile(seed=None) -> FingerprintProfile:
    """Build a coherent fingerprint profile.

    ``seed`` may be an int, a string (e.g. a session id, hashed deterministically),
    or ``None``/``0`` for a fresh random identity.  A non-zero seed always yields
    the same profile, so a session can keep one stable identity across pages.
    """
    resolved = _seed_from(seed)
    if not resolved:
        resolved = random.randint(_SEED_MIN, _SEED_MAX)
    rng = random.Random(resolved)

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
    timezone, locale, accept_language = rng.choice(_TZ_LOCALE)
    version, webkit = rng.choice(_SAFARI_VERSIONS)
    user_agent = _SAFARI_UA_TEMPLATE.format(version=version, webkit=webkit)

    return FingerprintProfile(
        seed=resolved,
        user_agent=user_agent,
        platform="MacIntel",
        vendor="Apple Computer, Inc.",
        webgl_vendor="Apple Inc.",
        webgl_renderer=renderer,
        hardware_concurrency=hw,
        device_memory=device_memory,
        viewport=viewport,
        timezone=timezone,
        locale=locale,
        accept_language=accept_language,
        max_touch_points=0,
    )
