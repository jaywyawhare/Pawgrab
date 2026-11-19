"""Coverage + latency benchmark (F7).

Measures, over a list of URLs, what fraction Pawgrab fetches successfully (coverage)
and the P50/P95 end-to-end latency, broken down by which fetch tier served each page
(curl_cffi / stealth browser / proxy browser). Numbers are *measured*, never claimed
— publish only what this prints.

    python -m benchmarks.coverage urls.txt
    python -m benchmarks.coverage --urls https://a.com https://b.com

Reads the fetch-tier counters from engine.metrics, so run it against a fresh process.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time


async def _measure(urls: list[str]) -> dict:
    from pawgrab.dependencies import try_browser_pool
    from pawgrab.engine.metrics import metrics
    from pawgrab.engine.scrape_service import scrape_url

    pool = await try_browser_pool()
    latencies: list[float] = []
    ok = 0
    for url in urls:
        start = time.perf_counter()
        try:
            resp = await scrape_url(url, formats=["markdown"], browser_pool=pool)
            if resp.success and (resp.markdown or resp.text):
                ok += 1
        except Exception:
            pass
        latencies.append(time.perf_counter() - start)

    latencies.sort()

    def _pct(p: float) -> float:
        if not latencies:
            return 0.0
        idx = min(len(latencies) - 1, int(p / 100 * len(latencies)))
        return round(latencies[idx], 3)

    return {
        "urls": len(urls),
        "coverage": round(ok / len(urls), 4) if urls else 0.0,
        "p50_s": _pct(50),
        "p95_s": _pct(95),
        "tiers": {
            "curl": metrics.fetch_tier_curl.value,
            "browser": metrics.fetch_tier_browser.value,
            "proxy": metrics.fetch_tier_proxy.value,
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", help="File with one URL per line")
    ap.add_argument("--urls", nargs="*", default=[])
    args = ap.parse_args()

    urls = list(args.urls)
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            urls += [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    if not urls:
        print("no URLs given", file=sys.stderr)
        raise SystemExit(2)

    import orjson

    result = asyncio.run(_measure(urls))
    sys.stdout.buffer.write(orjson.dumps(result, option=orjson.OPT_INDENT_2))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
