"""Anti-bot detection and stealth utilities.

Detects CAPTCHA challenges (Cloudflare, reCAPTCHA, hCaptcha, Turnstile) and
provides TLS fingerprint impersonation via curl_cffi to avoid triggering them.

Safari fingerprints are preferred because:
  - Most bots impersonate Chrome, so anti-bot systems scrutinise Chrome TLS
    fingerprints far more aggressively.
  - Safari uses Apple SecureTransport / Network.framework — a completely
    different TLS stack — so its JA3/JA4 hashes are distinct from the
    BoringSSL/OpenSSL signatures that Python clients normally emit.
  - Headless Safari doesn't exist outside macOS, so anti-bot allowlists
    trust Safari fingerprints more (real Safari traffic is almost never
    automated).
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

_CHALLENGE_SCAN_BYTES = 15_000


@dataclass(frozen=True, slots=True)
class _ChallengeRule:
    status_codes: frozenset[int] | None
    server_prefix: str | None
    body_pattern: re.Pattern[str]


@dataclass(frozen=True, slots=True)
class ChallengeDetection:
    """Result of a challenge/CAPTCHA check."""

    detected: bool
    challenge_type: str | None = None
    detail: str | None = None


def _compile_rules() -> dict[str, _ChallengeRule]:
    return {
        "cloudflare_js": _ChallengeRule(
            status_codes=frozenset({403, 429, 503}),
            server_prefix="cloudflare",
            body_pattern=re.compile(r"cdn-cgi/challenge-platform/\S+orchestrate/jsch/v1", re.I),
        ),
        "cloudflare_managed": _ChallengeRule(
            status_codes=frozenset({403, 503}),
            server_prefix="cloudflare",
            body_pattern=re.compile(r"cdn-cgi/challenge-platform/\S+orchestrate/(captcha|managed)/v1", re.I),
        ),
        "cloudflare_turnstile": _ChallengeRule(
            status_codes=frozenset({403, 503}),
            server_prefix=None,
            body_pattern=re.compile(r"challenges\.cloudflare\.com/turnstile", re.I),
        ),
        "cloudflare_interstitial": _ChallengeRule(
            status_codes=frozenset({403, 503}),
            server_prefix="cloudflare",
            body_pattern=re.compile(r"Just a moment\.\.\.", re.I),
        ),
        "recaptcha": _ChallengeRule(
            status_codes=None,
            server_prefix=None,
            body_pattern=re.compile(r"(google\.com/recaptcha|g-recaptcha|grecaptcha)", re.I),
        ),
        "hcaptcha": _ChallengeRule(
            status_codes=None,
            server_prefix=None,
            body_pattern=re.compile(r"(hcaptcha\.com|h-captcha)", re.I),
        ),
        "aws_waf": _ChallengeRule(
            status_codes=frozenset({403, 405}),
            server_prefix=None,
            body_pattern=re.compile(r"(awswaf|aws-waf-token|captcha\.awswaf\.com)", re.I),
        ),
        "akamai": _ChallengeRule(
            status_codes=frozenset({403, 429, 503}),
            server_prefix=None,
            body_pattern=re.compile(r"(/_sec/cp_challenge|akamai.*bot.*manager|akam/\d+/)", re.I),
        ),
        "imperva": _ChallengeRule(
            status_codes=frozenset({403, 429}),
            server_prefix=None,
            body_pattern=re.compile(r"(incapsula|visid_incap|_incap_ses|reese84)", re.I),
        ),
        "datadome": _ChallengeRule(
            status_codes=frozenset({403}),
            server_prefix=None,
            body_pattern=re.compile(r"(datadome\.co|dd\.js|api\.datadome\.co)", re.I),
        ),
        "perimeterx": _ChallengeRule(
            status_codes=frozenset({403, 429}),
            server_prefix=None,
            body_pattern=re.compile(r"(perimeterx|px-captcha|captcha\.px-cdn\.net|human-challenge)", re.I),
        ),
        "sucuri": _ChallengeRule(
            status_codes=frozenset({403}),
            server_prefix="sucuri",
            body_pattern=re.compile(r"(sucuri\.net|cloudproxy|access denied.*sucuri)", re.I),
        ),
        "meta_refresh": _ChallengeRule(
            status_codes=None,
            server_prefix=None,
            body_pattern=re.compile(r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]+url=', re.I),
        ),
        "generic_block": _ChallengeRule(
            status_codes=frozenset({403, 429}),
            server_prefix=None,
            body_pattern=re.compile(
                r"(bot detected|automated access|Please verify you are (a )?human|"
                r"unusual traffic from your computer)",
                re.I,
            ),
        ),
    }


_RULES = _compile_rules()


def detect_challenge(
    status_code: int,
    headers: dict[str, str],
    body: str,
) -> ChallengeDetection:
    """Check an HTTP response for CAPTCHA / anti-bot challenges."""
    server = headers.get("server", headers.get("Server", "")).lower()
    snippet = body[:_CHALLENGE_SCAN_BYTES]

    for name, rule in _RULES.items():
        if rule.status_codes and status_code not in rule.status_codes:
            continue
        if rule.server_prefix and not server.startswith(rule.server_prefix):
            continue
        if rule.body_pattern.search(snippet):
            return ChallengeDetection(
                detected=True,
                challenge_type=name,
                detail=f"Detected {name} challenge (HTTP {status_code})",
            )

    return ChallengeDetection(detected=False)


SAFARI_TARGETS = [
    "safari184",  # Safari 18.4 macOS (current stable)
    "safari180",  # Safari 18.0 macOS
    "safari170",  # Safari 17.0 macOS
    "safari184_ios",  # Safari 18.4 iOS
    "safari180_ios",  # Safari 18.0 iOS
    "safari172_ios",  # Safari 17.2 iOS
]

CHROME_TARGETS = [
    "chrome136",
    "chrome131",
    "chrome124",
    "chrome123",
]

EDGE_TARGETS = [
    "edge101",
    "edge99",
]

IMPERSONATE_TARGETS = SAFARI_TARGETS + CHROME_TARGETS + EDGE_TARGETS


def random_impersonate() -> str:
    """Pick a random browser impersonation target, heavily weighted to Safari.

    Weight distribution:
      - 70 % Safari  (macOS + iOS)
      - 20 % Chrome
      - 10 % Edge
    """
    roll = random.random()
    if roll < 0.70:
        return random.choice(SAFARI_TARGETS)
    if roll < 0.90:
        return random.choice(CHROME_TARGETS)
    return random.choice(EDGE_TARGETS)


def _impersonate_family(target: str) -> str:
    """Return 'safari', 'chrome', or 'edge' for a given target string."""
    if target.startswith("safari"):
        return "safari"
    if target.startswith("edge"):
        return "edge"
    return "chrome"


def fallback_impersonate(failed_target: str) -> str:
    """Pick a target from a *different* browser family than the one that failed.

    Switching families changes the entire TLS fingerprint (JA3 hash, cipher
    suite ordering, HTTP/2 framing) — the most effective way to dodge a
    fingerprint-based block.
    """
    failed_family = _impersonate_family(failed_target)

    # Prefer Safari when falling back from Chrome/Edge
    if failed_family != "safari":
        return random.choice(SAFARI_TARGETS)

    # Safari got blocked (rare, e.g. Amazon WAF) — fall back to Chrome
    return random.choice(CHROME_TARGETS)


_SAFARI_VERSIONS = [
    ("17.5", "605.1.15", "17.5"),
    ("17.6", "605.1.15", "17.6"),
    ("18.0", "605.1.15", "18.0"),
    ("18.3", "605.1.15", "18.3"),
    ("18.4", "605.1.15", "18.4"),
]

_SAFARI_UA_TEMPLATE = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/{webkit} (KHTML, like Gecko) Version/{version} Safari/{webkit}"


def random_user_agent() -> str:
    """Generate a realistic Safari macOS user-agent string."""
    version, webkit, _ = random.choice(_SAFARI_VERSIONS)
    return _SAFARI_UA_TEMPLATE.format(version=version, webkit=webkit)


_TZ_ACCEPT_LANG = {
    "America/New_York": "en-US,en;q=0.{q}",
    "America/Chicago": "en-US,en;q=0.{q}",
    "America/Denver": "en-US,en;q=0.{q}",
    "America/Los_Angeles": "en-US,en;q=0.{q}",
    "Europe/London": "en-GB,en;q=0.{q}",
    "Europe/Berlin": "en-DE,en-US;q=0.{q},en;q=0.{q2}",
    "Europe/Paris": "en-FR,en-US;q=0.{q},en;q=0.{q2}",
}


def _accept_language_for_tz(timezone: str | None = None) -> str:
    """Generate a realistic Accept-Language header matching the timezone."""
    q = random.randint(85, 95)  # randomize quality factor
    q2 = random.randint(70, 84)
    template = _TZ_ACCEPT_LANG.get(timezone or "", "en-US,en;q=0.{q}")
    return template.format(q=q, q2=q2)


def stealth_headers(
    user_agent: str | None = None,
    timezone: str | None = None,
) -> dict[str, str]:
    """Build a realistic set of HTTP headers matching a Safari browser.

    Only used for the Playwright path.  The curl_cffi path gets proper
    headers automatically from the impersonate target.
    """
    ua = user_agent or random_user_agent()
    accept_lang = _accept_language_for_tz(timezone)

    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": accept_lang,
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }


_REFERER_SOURCES = [
    "https://www.google.com/",
    "https://www.google.com/search?q=",
    "https://www.bing.com/search?q=",
    "https://duckduckgo.com/?q=",
    None,  # direct navigation (no referer)
    None,  # weight direct more
]


def random_referer() -> str | None:
    """Pick a random referer header to look like organic traffic."""
    return random.choice(_REFERER_SOURCES)
