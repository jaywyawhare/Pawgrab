"""Live anti-bot benchmark against public detection endpoints.

Drives the same fetch path the API uses (curl_cffi TLS impersonation with
browser escalation) against public bot-detection services and reports a real,
reproducible score per check. Network-dependent — run manually, not in CI:

    python -m benchmarks.stealth
    python -m benchmarks.stealth --json stealth-results.json
    python -m benchmarks.stealth --markdown docs/anti-bot-results.md

Checks:
    - tls_echo     TLS/JA3 fingerprint echo — proves impersonation produces a
                   browser-like JA3/JA4, not a Python/requests signature.
    - sannysoft    property-based checks (webdriver, chrome object, plugins…);
                   scored by counting passed vs. failed result cells.
    - incolumitas  behavioural/TLS scoring page (reachability + challenge only;
                   its scores are computed client-side and not measured here).

The judge functions are pure (HTML/JSON in, score out) so they are unit-tested
offline in tests/test_benchmark.py without touching the network.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, field

from pawgrab.engine.fetcher import close_sessions, fetch_page


@dataclass
class Judgement:
    """Result of scoring one detection page."""

    score: float | None  # 0..1, or None when the page cannot be scored statically
    ok: bool
    detail: str
    metrics: dict = field(default_factory=dict)


_BOT_UA_MARKERS = ("python", "curl", "aiohttp", "httpx", "go-http", "requests", "scrapy")


def judge_tls_echo(body: str) -> Judgement:
    """Score a TLS fingerprint echo (e.g. tls.peet.ws/api/all JSON).

    Passes when a JA3/JA4 fingerprint is present and the reported user agent
    looks like a real browser rather than an HTTP library.
    """
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return Judgement(None, False, "response was not JSON")
    tls = data.get("tls") or {}
    ja3 = tls.get("ja3") or tls.get("ja3_hash") or data.get("ja3")
    ja4 = tls.get("ja4") or data.get("ja4")
    ua = (data.get("user_agent") or data.get("http_version") or "").lower()
    has_fp = bool(ja3 or ja4)
    looks_like_bot = any(m in ua for m in _BOT_UA_MARKERS)
    ok = has_fp and not looks_like_bot
    detail = "browser-like TLS fingerprint" if ok else "missing fingerprint or library UA"
    return Judgement(
        1.0 if ok else 0.0,
        ok,
        detail,
        {"ja3": ja3, "ja4": ja4, "user_agent": data.get("user_agent")},
    )


def judge_sannysoft(html: str) -> Judgement:
    """Score bot.sannysoft.com by counting passed vs. failed result cells."""
    passed = len(re.findall(r'class="[^"]*\bpassed\b[^"]*"', html))
    failed = len(re.findall(r'class="[^"]*\bfailed\b[^"]*"', html))
    total = passed + failed
    if total == 0:
        return Judgement(None, False, "no result cells found (page may need JS rendering)")
    score = passed / total
    ok = score >= 0.85
    return Judgement(
        round(score, 4),
        ok,
        f"{passed}/{total} checks passed",
        {"passed": passed, "failed": failed},
    )


def judge_incolumitas(html: str) -> Judgement:
    """bot.incolumitas.com computes scores client-side; we only confirm reach."""
    reached = "incolumitas" in html.lower() or "detection" in html.lower()
    return Judgement(
        None,
        reached,
        "reached scoring page (scores are client-side; not measured here)" if reached else "did not reach page",
    )


CHECKS = [
    {"name": "tls_echo", "url": "https://tls.peet.ws/api/all", "judge": judge_tls_echo, "wait_for_js": False},
    {"name": "sannysoft", "url": "https://bot.sannysoft.com/", "judge": judge_sannysoft, "wait_for_js": True},
    {"name": "incolumitas", "url": "https://bot.incolumitas.com/?bot=1", "judge": judge_incolumitas, "wait_for_js": True},
]


async def run(checks: list[dict] | None = None) -> list[dict]:
    # A browser pool is required for the JS-rendered checks (e.g. sannysoft's
    # result table is populated client-side); without it fetch_page never
    # escalates past the plain-HTTP path even when wait_for_js is True.
    browser_pool = None
    try:
        from pawgrab.dependencies import try_browser_pool

        browser_pool = await try_browser_pool()
    except Exception:
        browser_pool = None

    results = []
    for check in checks or CHECKS:
        try:
            result = await fetch_page(
                check["url"],
                timeout=45_000,
                wait_for_js=check.get("wait_for_js"),
                browser_pool=browser_pool,
            )
            judgement: Judgement = check["judge"](result.html)
            blocked = result.status_code in (403, 429, 503)
            results.append(
                {
                    "site": check["name"],
                    "status": result.status_code,
                    "used_browser": result.used_browser,
                    "challenge": result.challenge.challenge_type if result.challenge else None,
                    "score": judgement.score,
                    "ok": judgement.ok and not blocked,
                    "detail": judgement.detail,
                    "metrics": judgement.metrics,
                }
            )
        except Exception as exc:
            results.append({"site": check["name"], "ok": False, "score": None, "detail": f"error: {exc}"})
    return results


def _fmt_score(score: float | None) -> str:
    return "—" if score is None else f"{score:.0%}"


def render_markdown(results: list[dict]) -> str:
    lines = [
        "| Check | Result | Score | Status | Browser | Challenge | Detail |",
        "|-------|--------|------:|:------:|:-------:|:---------:|--------|",
    ]
    for r in results:
        flag = "✅ pass" if r["ok"] else "❌ fail"
        lines.append(
            f"| {r['site']} | {flag} | {_fmt_score(r.get('score'))} | {r.get('status', '-')} | {r.get('used_browser', '-')} | {r.get('challenge') or '-'} | {r['detail']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Live anti-bot benchmark")
    parser.add_argument("--json", dest="json_path", default=None, help="also write results as JSON")
    parser.add_argument("--markdown", dest="md_path", default=None, help="also write a markdown results table")
    args = parser.parse_args()
    results = asyncio.run(run())
    width = max(len(r["site"]) for r in results)
    for r in results:
        flag = "PASS" if r["ok"] else "FAIL"
        print(f"{r['site']:<{width}}  {flag}  score={_fmt_score(r.get('score'))}  status={r.get('status', '-')}  browser={r.get('used_browser', '-')}  {r['detail']}")
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2)
    if args.md_path:
        with open(args.md_path, "w", encoding="utf-8") as fh:
            fh.write(render_markdown(results))
    passed = sum(1 for r in results if r["ok"])
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


async def _shutdown() -> None:
    await close_sessions()
    try:
        from pawgrab.dependencies import shutdown_browser_pool

        await shutdown_browser_pool()
    except Exception:
        pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        asyncio.run(_shutdown())
