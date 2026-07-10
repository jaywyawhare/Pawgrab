"""Run Pawgrab's extraction against the WCXB benchmark and emit predictions.

WCXB (https://github.com/Murrough-Foley/web-content-extraction-benchmark) is a
2,008-page, 7-page-type, frozen-HTML benchmark for main-content extraction. Unlike
the live-URL scrape-evals harness, it is fully reproducible and isolates extraction
quality (no fetch / anti-bot noise), covering the non-article layouts (product,
forum, listing, collection, docs, service) where extractors diverge most.

Usage:
    python -m benchmarks.external.wcxb_runner --wcxb-dir /path/to/wcxb --split dev
    # writes predictions to wcxb_predictions_<split>.json, then:
    python /path/to/wcxb/evaluate.py --split dev --results wcxb_predictions_dev.json --per-type

This runner also prints its own per-page-type word-F1 using the same scoring as
WCXB's evaluate.py, so a single command gives the full breakdown.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path


def _extract_one(args: tuple[str, str, str]) -> tuple[str, str]:
    file_id, html, url = args
    from benchmarks.run import extract_text

    try:
        return file_id, extract_text(html, url=url)
    except Exception:
        return file_id, ""


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", (text or "").lower())


def _word_f1(pred: str, ref: str) -> tuple[float, float, float]:
    from collections import Counter

    pt, rt = _tokenize(pred), _tokenize(ref)
    if not pt or not rt:
        return (0.0, 0.0, 0.0)
    overlap = sum((Counter(pt) & Counter(rt)).values())
    p = overlap / len(pt)
    r = overlap / len(rt)
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return (p, r, f1)


def load_cases(wcxb_dir: Path, split: str, limit: int | None) -> list[tuple[str, str, str, str]]:
    """Return (file_id, html, url, page_type) for each page in the split."""
    gt_dir = wcxb_dir / split / "ground-truth"
    html_dir = wcxb_dir / split / "html"
    cases = []
    for gt_path in sorted(gt_dir.glob("*.json")):
        file_id = gt_path.stem
        gt = json.loads(gt_path.read_text())
        g = gt.get("ground_truth", {})
        url = gt.get("url", "")
        page_type = (gt.get("_internal", {}).get("page_type", {}) or {}).get("primary", "unknown")
        html_path = html_dir / f"{file_id}.html.gz"
        if not html_path.exists():
            continue
        with gzip.open(html_path, "rt", encoding="utf-8", errors="replace") as fh:
            html = fh.read()
        cases.append((file_id, html, url, page_type, g.get("main_content", "") or ""))
        if limit and len(cases) >= limit:
            break
    return cases


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wcxb-dir", required=True, type=Path)
    ap.add_argument("--split", default="dev", choices=["dev", "test"])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args(argv)

    cases = load_cases(args.wcxb_dir, args.split, args.limit)
    print(f"Loaded {len(cases)} WCXB pages ({args.split})")

    t0 = time.perf_counter()
    payload = [(fid, html, url) for fid, html, url, _pt, _gt in cases]
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        preds = dict(ex.map(_extract_one, payload, chunksize=8))
    dt = time.perf_counter() - t0
    print(f"Extracted {len(preds)} pages in {dt:.1f}s ({dt / max(len(preds),1) * 1000:.0f} ms/page)")

    out = args.out or Path(f"wcxb_predictions_{args.split}.json")
    out.write_text(json.dumps(preds))
    print(f"Predictions -> {out}")

    # Score ourselves, per page type (same word-F1 as WCXB evaluate.py).
    by_type: dict[str, list[tuple[float, float, float]]] = {}
    allrows: list[tuple[float, float, float]] = []
    for fid, _html, _url, pt, gt in cases:
        s = _word_f1(preds.get(fid, ""), gt)
        by_type.setdefault(pt, []).append(s)
        allrows.append(s)

    def avg(rows, i):
        return sum(r[i] for r in rows) / len(rows) if rows else 0.0

    print(f"\n{'page_type':<16}{'n':>6}{'P':>8}{'R':>8}{'F1':>8}")
    print("-" * 46)
    for pt in sorted(by_type, key=lambda k: -len(by_type[k])):
        rows = by_type[pt]
        print(f"{pt:<16}{len(rows):>6}{avg(rows,0):>8.3f}{avg(rows,1):>8.3f}{avg(rows,2):>8.3f}")
    print("-" * 46)
    print(f"{'OVERALL':<16}{len(allrows):>6}{avg(allrows,0):>8.3f}{avg(allrows,1):>8.3f}{avg(allrows,2):>8.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
