# Extraction benchmark

A reproducible benchmark for pawgrab's **content-extraction quality** — how well
`extract_content` isolates the main article prose from boilerplate (nav bars,
sidebars, cookie banners, share widgets, footers).

> The `assets/bench.svg` chart in the project README measures **scraping speed**
> (end-to-end latency vs. other libraries). That's a separate axis. This harness
> measures **what** is extracted, not how fast.

## What it measures

For every case the harness runs the same path the CLI and API use —
`extract_content(html) → convert(..., TEXT)` — and compares the output against a
hand-written ground-truth main content using a bag-of-tokens
**precision / recall / F1**:

- **recall** falls when real article text is dropped,
- **precision** falls when boilerplate leaks into the output,
- **F1** is the harmonic mean reported per case and averaged.

## Layout

```
benchmarks/
  score.py            dependency-free P/R/F1 scoring
  run.py              driver: extract, score, report
  dataset/
    manifest.json     ordered list of cases
    <case>/
      page.html       raw HTML as fetched
      expected.txt    ground-truth main content (plain prose)
```

## Running

```bash
pip install -e ".[dev]"          # extraction needs readability/trafilatura/bs4
python -m benchmarks.run                        # print a table
python -m benchmarks.run --json results.json    # also dump JSON
python -m benchmarks.run --min-f1 0.85          # non-zero exit on regression
```

## Adding a case

1. Save the page's raw HTML to `dataset/<name>/page.html`.
2. Write the expected main content (headings + prose, no chrome) to
   `dataset/<name>/expected.txt`.
3. Add `<name>` to `dataset/manifest.json`.

Keep ground truth as plain prose: scoring is token-based, so exact markdown or
whitespace doesn't matter, but leaked nav/footer words will (correctly) cost
precision.

## Regression gate

`tests/test_benchmark.py` unit-tests the scorer (always) and runs the full
extraction over the seed dataset when the extraction deps are installed,
asserting a minimum mean F1. Wire `python -m benchmarks.run --min-f1 <t>` into
CI to fail builds that regress extraction quality.
