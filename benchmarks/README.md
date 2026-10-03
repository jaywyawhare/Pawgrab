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

# Framework comparison

`benchmarks/compare.py` runs Pawgrab's extraction pipeline against other
open-source frameworks over the same dataset cases, scored with the same
bag-of-tokens F1:

```bash
pip install -e ".[dev]" trafilatura goose3 scrapy aiohttp
python -m benchmarks.compare                 # quality + latency table
python -m benchmarks.compare --live          # end-to-end network comparison
python -m benchmarks.compare --json out.json
```

Latest results (`--repeat 5`, this dataset):

| framework      | mean F1 | min F1 | med ms |
|----------------|--------:|-------:|-------:|
| pawgrab        |   1.000 |  1.000 |   30.9 |
| trafilatura    |   0.996 |  0.978 |   11.4 |
| readability    |   0.993 |  0.964 |    8.9 |
| goose3         |   0.983 |  0.955 |   27.6 |
| scrapy(parsel) |   0.876 |  0.775 |    3.3 |
| bs4(raw)       |   0.859 |  0.759 |    4.4 |

Notes: `bs4(raw)`/`scrapy(parsel)` are faster because they return *all* page
text (nav/footer/ads included) rather than article-quality main content.
`--live` measures end-to-end fetch+extract; Pawgrab's numbers include its
full fetch stack (robots.txt, rate limiting, session warming, TLS
impersonation) which the others don't perform.
