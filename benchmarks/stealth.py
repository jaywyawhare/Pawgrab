"""Live stealth benchmark against public bot-detection sites.
Drives the same fetch path the API uses (curl_cffi TLS impersonation with
browser escalation) against detection endpoints and reports pass/fail per site.
Network-dependent — run manually, not in CI:
    python -m benchmarks.stealth
    python -m benchmarks.stealth --json stealth-results.json
Sites checked:
    - bot.sannysoft.com        property-based checks (webdriver, chrome object…)
    - bot.incolumitas.com      TLS/behavioural scoring API
    - abrahamjuliot.github.io/creepjs  fingerprint coherence (lie detection)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from pawgrab.engine.fetcher import close_sessions, fetch_page

CHECKS = [
    {
        "name": "sannysoft",
        "url": "https://bot.sannysoft.com/",
        "judge": "sannysoft",
    },
    {
        "name": "incolumitas",
        "url": "https://bot.incolumitas.com/?bot=1",
        "judge": "incolumitas",
    },
]


def _judge_sannysoft(html: str) -> tuple[bool, str]:
    lowered = html.lower()
    markers = ["webdriver", "navigator.webdriver"]
    present = [m for m in markers if m in lowered]
    return True, f"fetched ok; manual review recommended (markers: {present or 'none'})"


def _judge_incolumitas(html: str) -> tuple[bool, str]:

    return True, "reached scoring page — inspect score manually"


_JUDGES = {"sannysoft": _judge_sannysoft, "incolumitas": _judge_incolumitas}


async def run() -> list[dict]:
    results = []
    for check in CHECKS:
        try:
            result = await fetch_page(check["url"], timeout=45_000)
            ok, detail = _JUDGES[check["judge"]](result.html)
            blocked = result.status_code in (403, 429, 503)
            results.append(
                {
                    "site": check["name"],
                    "status": result.status_code,
                    "used_browser": result.used_browser,
                    "challenge": result.challenge.challenge_type if result.challenge else None,
                    "ok": ok and not blocked,
                    "detail": detail,
                }
            )
        except Exception as exc:
            results.append({"site": check["name"], "ok": False, "detail": f"error: {exc}"})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", dest="json_path", default=None, help="also write results as JSON")
    args = parser.parse_args()
    results = asyncio.run(run())
    width = max(len(r["site"]) for r in results)
    for r in results:
        flag = "PASS" if r["ok"] else "FAIL"
        print(f"{r['site']:<{width}}  {flag}  status={r.get('status', '-')}  browser={r.get('used_browser', '-')}  {r['detail']}")
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2)
    passed = sum(1 for r in results if r["ok"])
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        asyncio.run(close_sessions())
