"""Framework comparison: extraction quality (F1) + latency on the shared dataset.

Runs every framework over the same local HTML cases and scores main-content
extraction against the ground truth with the same bag-of-tokens F1 used by
`benchmarks.run`. Latency is wall-clock per case (median of runs).

    python -m benchmarks.compare
    python -m benchmarks.compare --repeat 3 --json compare.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from score import score_tokens  # bag-of-tokens P/R/F1


def load_cases(dataset: Path):
    names = [p.name for p in sorted(dataset.iterdir()) if p.is_dir()]
    return [(n, (dataset / n / "page.html").read_text(encoding="utf-8"), (dataset / n / "expected.txt").read_text(encoding="utf-8")) for n in names]


# --- framework adapters: html -> extracted plain text ---


def fw_pawgrab(html: str) -> str:
    from pawgrab.engine.cleaner import extract_content
    from pawgrab.engine.converter import convert
    from pawgrab.models.common import OutputFormat

    cleaned = extract_content(html)
    return convert(cleaned.content_html, OutputFormat.TEXT)


def fw_trafilatura(html: str) -> str:
    import trafilatura

    return trafilatura.extract(html, output_format="txt", include_comments=False, include_tables=True) or ""


def fw_readability(html: str) -> str:
    from bs4 import BeautifulSoup
    from readability import Document

    doc = Document(html)
    return BeautifulSoup(doc.summary(), "lxml").get_text(" ", strip=True)


def fw_goose3(html: str) -> str:
    from bs4 import BeautifulSoup
    from goose3 import Goose

    with Goose({"enable_image_fetching": False, "parser_class": "lxml"}) as g:
        article = g.extract(raw_html=html)
    text = article.cleaned_text or ""
    # goose returns newline-joined prose; normalise to spaces for scoring parity.
    return " ".join(BeautifulSoup(f"<p>{text}</p>", "lxml").get_text(" ", strip=True).split())


def fw_scrapy_parsel(html: str) -> str:
    """Scrapy's selector layer + a generic article heuristic ('//article' fallback body)."""
    from parsel import Selector

    sel = Selector(text=html)
    xp = "//article | //main | //*[@role='main'] | //body"
    node = sel.xpath(xp).get() or sel.xpath("//body").get() or ""
    text = Selector(text=node).xpath("//text()").getall()
    return " ".join(" ".join(t.strip() for t in text if t.strip()).split())


def fw_bs4_raw(html: str) -> str:
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "lxml").get_text(" ", strip=True)


FRAMEWORKS = {
    "pawgrab": fw_pawgrab,
    "trafilatura": fw_trafilatura,
    "readability": fw_readability,
    "goose3": fw_goose3,
    "scrapy(parsel)": fw_scrapy_parsel,
    "bs4(raw)": fw_bs4_raw,
}


LIVE_URLS = [
    "https://books.toscrape.com/",
    "https://quotes.toscrape.com/",
    "https://blog.python.org/",
]


async def live_round(url: str) -> dict:
    """End-to-end (network fetch + extraction) per framework on one URL."""
    import aiohttp

    out = {}
    async with aiohttp.ClientSession() as http:
        t0 = time.perf_counter()
        async with http.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            html = await resp.text()
        plain_ms = (time.perf_counter() - t0) * 1000

        for fw_name, fn in FRAMEWORKS.items():
            if fw_name == "pawgrab":
                continue
            t0 = time.perf_counter()
            try:
                text = fn(html)
                out[fw_name] = {"ok": bool(text.strip()), "ms": round((time.perf_counter() - t0) * 1000, 1)}
            except Exception as exc:
                out[fw_name] = {"ok": False, "error": type(exc).__name__}

        # Pawgrab uses its own fetch stack (TLS impersonation), not aiohttp's.
        from pawgrab.engine.fetcher import fetch_page

        t0 = time.perf_counter()
        result = await fetch_page(url, timeout=30_000)
        text = fw_pawgrab(result.html or "")
        out["pawgrab"] = {
            "ok": bool(text.strip()),
            "ms": round((time.perf_counter() - t0) * 1000, 1),
            "status": result.status_code,
        }
    out["_plain_fetch_ms"] = round(plain_ms, 1)
    return out


def run_live(urls) -> list[dict]:
    import asyncio

    async def all_urls():
        return [(u, await live_round(u)) for u in urls]

    rows = asyncio.run(all_urls())
    for url, res in rows:
        print(f"\n{url}  (plain fetch: {res.pop('_plain_fetch_ms')} ms)")
        for fw, data in sorted(res.items()):
            status = f"ok {data['ms']:>7.1f} ms" if data.get("ok") else f"FAILED ({data.get('error', 'empty')})"
            extra = f"  http={data['status']}" if data.get("status") else ""
            print(f"  {fw:<16} {status}{extra}")
    return [{"url": u, **r} for u, r in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path(__file__).parent / "dataset")
    parser.add_argument("--repeat", type=int, default=3, help="timing repetitions per case")
    parser.add_argument("--live", action="store_true", help="end-to-end network comparison instead of dataset scoring")
    parser.add_argument("--urls", nargs="*", default=None, help="URLs for --live mode")
    parser.add_argument("--json", dest="json_path", type=Path, default=None)
    args = parser.parse_args()

    if args.live:
        results = run_live(args.urls or LIVE_URLS)
        if args.json_path:
            args.json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        return 0

    cases = load_cases(args.dataset)
    rows = {name: {"f1": [], "ms": []} for name in FRAMEWORKS}

    for name, html, expected in cases:
        for fw_name, fn in FRAMEWORKS.items():
            try:
                t0 = time.perf_counter()
                text = fn(html)
                dt = (time.perf_counter() - t0) * 1000
                f1 = score_tokens(text, expected).f1
                rows[fw_name]["f1"].append(f1)
                rows[fw_name]["ms"].append(dt)
            except Exception as exc:
                print(f"warn: {fw_name} failed on {name}: {type(exc).__name__}: {exc}", file=sys.stderr)

    header = f"{'framework':<16} {'mean F1':>8} {'min F1':>8} {'med ms':>8}"
    print(header)
    print("-" * len(header))
    results = {}
    for fw_name, data in rows.items():
        if not data["f1"]:
            continue
        mean_f1 = statistics.mean(data["f1"])
        min_f1 = min(data["f1"])
        med_ms = statistics.median(data["ms"])
        results[fw_name] = {"mean_f1": round(mean_f1, 4), "min_f1": round(min_f1, 4), "median_ms": round(med_ms, 2)}
        print(f"{fw_name:<16} {mean_f1:>8.3f} {min_f1:>8.3f} {med_ms:>8.1f}")

    if args.json_path:
        args.json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    best_q = max(results, key=lambda k: results[k]["mean_f1"])
    best_s = min(results, key=lambda k: results[k]["median_ms"])
    print(f"\nbest quality: {best_q}   fastest: {best_s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
