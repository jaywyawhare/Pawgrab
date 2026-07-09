"""Run the extraction-quality + latency benchmark over pawgrab's pipeline.

Each dataset case is a directory containing:
    page.html      raw HTML as fetched from the source
    expected.txt   ground-truth main content (plain prose, no boilerplate)

The harness drives the *same* extraction path the CLI/API use
(``extract_content`` -> ``convert(..., TEXT)``), scores the output against
``expected.txt`` with a bag-of-tokens F1, and times each extraction.

Examples:
    python -m benchmarks.run
    python -m benchmarks.run --json results.json --min-f1 0.70
    python -m benchmarks.run --dataset benchmarks/dataset
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from benchmarks.score import Score, mean_f1, score_tokens

DEFAULT_DATASET = Path(__file__).parent / "dataset"


def load_cases(dataset: Path) -> list[tuple[str, str, str]]:
    """Return ``(name, html, expected_text)`` for every case in the dataset."""
    manifest = dataset / "manifest.json"
    if manifest.exists():
        names = json.loads(manifest.read_text(encoding="utf-8"))["cases"]
    else:
        names = [p.name for p in sorted(dataset.iterdir()) if p.is_dir()]

    cases = []
    for name in names:
        case_dir = dataset / name
        html = (case_dir / "page.html").read_text(encoding="utf-8")
        expected = (case_dir / "expected.txt").read_text(encoding="utf-8")
        cases.append((name, html, expected))
    return cases


def extract_text(html: str, url: str = "") -> str:
    """Run pawgrab's extraction pipeline and return plain text.

    Imported lazily so ``score.py`` and this module's argument parsing stay
    usable even when pawgrab's heavier dependencies aren't installed.
    """
    from pawgrab.engine.cleaner import extract_content
    from pawgrab.engine.converter import convert
    from pawgrab.models.common import OutputFormat

    cleaned = extract_content(html, url=url)
    return convert(cleaned.content_html, OutputFormat.TEXT)


def run(dataset: Path) -> list[tuple[str, Score, float]]:
    """Extract + score every case; returns ``(name, score, latency_ms)``."""
    results = []
    for name, html, expected in load_cases(dataset):
        start = time.perf_counter()
        predicted = extract_text(html, url=f"https://example.com/{name}")
        latency_ms = (time.perf_counter() - start) * 1000
        results.append((name, score_tokens(predicted, expected), latency_ms))
    return results


def _print_table(results: list[tuple[str, Score, float]]) -> None:
    header = f"{'case':<28}{'P':>7}{'R':>7}{'F1':>7}{'latency':>11}"
    print(header)
    print("-" * len(header))
    for name, score, latency_ms in results:
        print(
            f"{name:<28}{score.precision:>7.3f}{score.recall:>7.3f}"
            f"{score.f1:>7.3f}{latency_ms:>9.1f}ms"
        )
    scores = [s for _, s, _ in results]
    n = len(results) or 1
    avg_p = sum(s.precision for s in scores) / n
    avg_r = sum(s.recall for s in scores) / n
    avg_latency = sum(lat for _, _, lat in results) / n
    print("-" * len(header))
    print(
        f"{'MEAN':<28}{avg_p:>7.3f}{avg_r:>7.3f}"
        f"{mean_f1(scores):>7.3f}{avg_latency:>9.1f}ms"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--json", type=Path, help="write full results as JSON")
    parser.add_argument(
        "--min-f1",
        type=float,
        default=None,
        help="exit non-zero if mean F1 falls below this (regression gate)",
    )
    args = parser.parse_args(argv)

    try:
        results = run(args.dataset)
    except ImportError as exc:
        print(
            f"pawgrab is not importable ({exc}). Install deps first:\n"
            '    pip install -e ".[dev]"',
            file=sys.stderr,
        )
        return 2

    _print_table(results)

    scores = [s for _, s, _ in results]
    avg_f1 = mean_f1(scores)

    if args.json:
        n = len(scores) or 1
        payload = {
            "mean_f1": round(avg_f1, 4),
            "mean_precision": round(sum(s.precision for s in scores) / n, 4),
            "mean_recall": round(sum(s.recall for s in scores) / n, 4),
            "cases": [
                {"name": name, **score.as_dict(), "latency_ms": round(lat, 1)}
                for name, score, lat in results
            ],
        }
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")

    if args.min_f1 is not None and avg_f1 < args.min_f1:
        print(
            f"\nFAIL: mean F1 {avg_f1:.3f} < threshold {args.min_f1:.3f}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
