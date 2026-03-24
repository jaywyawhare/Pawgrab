"""Tests for anti-bot detection and stealth utilities."""

from pawgrab.engine.antibot import (
    CHROME_TARGETS,
    EDGE_TARGETS,
    IMPERSONATE_TARGETS,
    SAFARI_TARGETS,
    _accept_language_for_tz,
    detect_challenge,
    fallback_impersonate,
    random_impersonate,
    random_referer,
    random_user_agent,
    stealth_headers,
)


def test_no_challenge_on_normal_page():
    result = detect_challenge(200, {}, "<html><body>Hello world</body></html>")
    assert result.detected is False
    assert result.challenge_type is None


def test_detect_cloudflare_js_challenge():
    body = """
    <html><head><title>Just a moment...</title></head>
    <body>
    <script>cpo.src = '/cdn-cgi/challenge-platform/h/b/orchestrate/jsch/v1?ray=abc'</script>
    </body></html>
    """
    result = detect_challenge(403, {"server": "cloudflare"}, body)
    assert result.detected is True
    assert result.challenge_type == "cloudflare_js"


def test_detect_cloudflare_managed_captcha():
    body = """<script>cpo.src='/cdn-cgi/challenge-platform/x/orchestrate/managed/v1'</script>"""
    result = detect_challenge(403, {"server": "cloudflare"}, body)
    assert result.detected is True
    assert result.challenge_type == "cloudflare_managed"


def test_detect_cloudflare_turnstile():
    body = """<script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>"""
    result = detect_challenge(403, {}, body)
    assert result.detected is True
    assert result.challenge_type == "cloudflare_turnstile"


def test_detect_cloudflare_interstitial():
    body = "<html><title>Just a moment...</title></html>"
    result = detect_challenge(503, {"server": "cloudflare"}, body)
    assert result.detected is True
    assert result.challenge_type == "cloudflare_interstitial"


def test_detect_recaptcha():
    body = '<div class="g-recaptcha" data-sitekey="abc"></div>'
    result = detect_challenge(200, {}, body)
    assert result.detected is True
    assert result.challenge_type == "recaptcha"


def test_detect_hcaptcha():
    body = '<div class="h-captcha" data-sitekey="abc"></div>'
    result = detect_challenge(200, {}, body)
    assert result.detected is True
    assert result.challenge_type == "hcaptcha"


def test_detect_generic_block():
    body = "<html><body><h1>bot detected</h1><p>You have been blocked.</p></body></html>"
    result = detect_challenge(403, {}, body)
    assert result.detected is True
    assert result.challenge_type == "generic_block"


def test_no_false_positive_on_403_without_markers():
    body = "<html><body><h1>Forbidden</h1><p>You don't have permission.</p></body></html>"
    result = detect_challenge(403, {}, body)
    assert result.detected is False


def test_cloudflare_requires_matching_server_header():
    body = """<script>cpo.src='/cdn-cgi/challenge-platform/x/orchestrate/jsch/v1'</script>"""
    result = detect_challenge(403, {"server": "nginx"}, body)
    assert result.challenge_type != "cloudflare_js"


def test_safari_targets_are_preferred():
    """Safari should make up the majority of the target list."""
    assert len(SAFARI_TARGETS) >= len(CHROME_TARGETS)
    assert len(SAFARI_TARGETS) >= len(EDGE_TARGETS)


def test_all_safari_targets_start_with_safari():
    for t in SAFARI_TARGETS:
        assert t.startswith("safari")


def test_impersonate_targets_is_safari_first():
    """IMPERSONATE_TARGETS should list Safari targets before Chrome/Edge."""
    first_non_safari = next(
        (i for i, t in enumerate(IMPERSONATE_TARGETS) if not t.startswith("safari")),
        len(IMPERSONATE_TARGETS),
    )
    assert first_non_safari == len(SAFARI_TARGETS)


def test_random_impersonate_returns_valid_target():
    target = random_impersonate()
    assert target in IMPERSONATE_TARGETS


def test_random_impersonate_heavily_favours_safari():
    """Over many samples, Safari should dominate."""
    targets = [random_impersonate() for _ in range(200)]
    safari_count = sum(1 for t in targets if t.startswith("safari"))
    # 70% weight → expect ~140 out of 200; allow generous margin
    assert safari_count > 80


def test_random_impersonate_varies():
    targets = {random_impersonate() for _ in range(50)}
    assert len(targets) > 1


def test_impersonate_targets_are_strings():
    for t in IMPERSONATE_TARGETS:
        assert isinstance(t, str)
        assert len(t) > 0


def test_fallback_from_chrome_goes_to_safari():
    for _ in range(20):
        target = fallback_impersonate("chrome124")
        assert target.startswith("safari")


def test_fallback_from_edge_goes_to_safari():
    for _ in range(20):
        target = fallback_impersonate("edge101")
        assert target.startswith("safari")


def test_fallback_from_safari_goes_to_chrome():
    for _ in range(20):
        target = fallback_impersonate("safari184")
        assert target.startswith("chrome")


def test_fallback_from_safari_ios_goes_to_chrome():
    for _ in range(20):
        target = fallback_impersonate("safari184_ios")
        assert target.startswith("chrome")


def test_random_user_agent_is_safari():
    ua = random_user_agent()
    assert "Safari/" in ua
    assert "Version/" in ua
    assert "Macintosh" in ua


def test_random_user_agent_varies():
    agents = {random_user_agent() for _ in range(20)}
    assert len(agents) > 1


def test_random_user_agent_no_chrome():
    """Safari UA should NOT contain 'Chrome/' — that's a Chrome UA."""
    for _ in range(20):
        ua = random_user_agent()
        assert "Chrome/" not in ua


def test_stealth_headers_safari_format():
    headers = stealth_headers()
    assert "User-Agent" in headers
    assert "Sec-Fetch-Dest" in headers
    assert headers["Sec-Fetch-Dest"] == "document"
    # Safari headers should NOT contain Chrome-specific Sec-Ch-Ua
    assert "Sec-Ch-Ua" not in headers


def test_stealth_headers_accept_matches_safari():
    headers = stealth_headers()
    # Safari uses a simpler Accept header than Chrome
    assert "text/html" in headers["Accept"]
    assert "avif" not in headers["Accept"]


def test_detect_aws_waf():
    body = '<script src="https://captcha.awswaf.com/x/abc.js"></script>'
    result = detect_challenge(403, {}, body)
    assert result.detected is True
    assert result.challenge_type == "aws_waf"


def test_detect_akamai_bot_manager():
    body = '<script src="/_sec/cp_challenge/verify"></script>'
    result = detect_challenge(403, {}, body)
    assert result.detected is True
    assert result.challenge_type == "akamai"


def test_detect_imperva():
    body = '<script>var visid_incap = "abc123";</script>'
    result = detect_challenge(403, {}, body)
    assert result.detected is True
    assert result.challenge_type == "imperva"


def test_detect_datadome():
    body = '<script src="https://api.datadome.co/js/123.js"></script>'
    result = detect_challenge(403, {}, body)
    assert result.detected is True
    assert result.challenge_type == "datadome"


def test_detect_perimeterx():
    body = '<div id="px-captcha" class="px-captcha"></div>'
    result = detect_challenge(403, {}, body)
    assert result.detected is True
    assert result.challenge_type == "perimeterx"


def test_detect_sucuri():
    body = '<p>Access denied by sucuri.net firewall</p>'
    result = detect_challenge(403, {"server": "sucuri/cloudproxy"}, body)
    assert result.detected is True
    assert result.challenge_type == "sucuri"


def test_detect_meta_refresh():
    body = '<html><head><meta http-equiv="refresh" content="5;url=https://example.com/verify"></head></html>'
    result = detect_challenge(200, {}, body)
    assert result.detected is True
    assert result.challenge_type == "meta_refresh"


def test_no_false_positive_access_denied_200():
    """Access Denied on a 200 should NOT be flagged (tightened generic_block)."""
    body = "<html><body><h1>Access Denied</h1></body></html>"
    result = detect_challenge(200, {}, body)
    assert result.detected is False


def test_stealth_headers_has_sec_fetch_user():
    headers = stealth_headers()
    assert headers.get("Sec-Fetch-User") == "?1"


def test_random_referer_returns_valid_or_none():
    for _ in range(50):
        ref = random_referer()
        if ref is not None:
            assert ref.startswith("https://")


def test_random_referer_varies():
    refs = {random_referer() for _ in range(100)}
    assert len(refs) > 1


def test_accept_language_matches_us_timezone():
    lang = _accept_language_for_tz("America/New_York")
    assert lang.startswith("en-US")


def test_accept_language_matches_uk_timezone():
    lang = _accept_language_for_tz("Europe/London")
    assert lang.startswith("en-GB")


def test_accept_language_varies_q_values():
    """q-values should be randomized, not static."""
    langs = {_accept_language_for_tz("America/New_York") for _ in range(50)}
    assert len(langs) > 1


def test_stealth_headers_with_timezone():
    headers = stealth_headers(timezone="Europe/London")
    assert headers["Accept-Language"].startswith("en-GB")


def test_stealth_headers_default_timezone():
    headers = stealth_headers()
    assert "en-US" in headers["Accept-Language"]
