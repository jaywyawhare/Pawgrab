# External benchmarks

The in-repo `benchmarks/` harness measures **extraction quality** on a handful of
hand-authored HTML fixtures. This directory adds two external benchmarks.

## WCXB — reproducible, typed extraction quality (preferred)

[WCXB](https://github.com/Murrough-Foley/web-content-extraction-benchmark) is a
2,008-page, **7-page-type**, frozen-HTML benchmark for main-content extraction.
Unlike scrape-evals it is fully reproducible (frozen HTML, no live fetch/anti-bot
noise) and — crucially — labels non-article layouts (product, forum, listing,
collection, docs, service) where extractors actually diverge.

```bash
git clone https://github.com/Murrough-Foley/web-content-extraction-benchmark wcxb
python -m benchmarks.external.wcxb_runner --wcxb-dir wcxb --split dev
# cross-check with the official scorer:
python wcxb/evaluate.py --split dev --results wcxb_predictions_dev.json --per-type
```

**Pawgrab results** (word-level F1; cross-validated against WCXB's `evaluate.py`):

| Split | F1 | Precision | Recall | Rank vs WCXB baselines |
|---|---|---|---|---|
| dev (1,497) | **0.808** | 0.807 | 0.867 | #3 of 12 |
| test (511) | **0.851** | 0.851 | 0.897 | #2 of shown |

Beats plain Trafilatura (dev 0.791 / test 0.833), dom-smoothie, ReaderLM-v2,
Newspaper4k and Readability (0.675); behind only **rs-trafilatura** (0.859/0.893)
and neural MinerU-HTML (0.827).

**Per-type (dev)** — where the headroom is:

| Type | Pawgrab | rs-traf (best) | plain Trafilatura |
|---|---|---|---|
| article | 0.928 | 0.932 | 0.926 |
| documentation | 0.919 | 0.932 | 0.888 |
| service | 0.777 | 0.844 | 0.763 |
| listing | 0.609 | 0.707 | 0.589 |
| collection | 0.588 | 0.716 | 0.553 |
| forum | 0.587 | 0.808 | 0.585 |
| product | 0.557 | 0.641 | 0.567 |

Top-tier on article/docs; beats plain Trafilatura on most structured types; the
real gaps to close are **forum** (0.587 vs rs-traf 0.808) and **product precision**
(0.504 — boilerplate leaks in). This is the safe, reproducible target for the
non-article extraction work.

## scrape-evals — end-to-end (fetch + anti-bot + extraction)

The external [`scrape-evals`](https://github.com/martynasoxylabs/scrape-evals)
benchmark measures **end-to-end scraping** over 1,000 live, annotated web pages,
and reports:

- **Coverage** — fraction of pages returned with a valid (2xx, non-empty,
  non-block-page) response.
- **Quality F1** — best-window bag-of-tokens recall/precision of the extracted
  text against a human-curated `truth_text` (with `lie_text` noise penalties).

## How to run

```bash
git clone https://github.com/martynasoxylabs/scrape-evals
cd scrape-evals
pip install -e /path/to/Pawgrab          # installs pawgrab + deps
pip install typer requests pandas         # scrape-evals runtime deps

cp /path/to/Pawgrab/benchmarks/external/pawgrab_scraper.py engines/
cp /path/to/Pawgrab/benchmarks/external/pawgrab_browser_scraper.py engines/

# robots off => apples-to-apples with the other engines, which ignore robots.txt
PAWGRAB_RESPECT_ROBOTS=false python run_eval.py \
    --scrape_engine pawgrab_scraper \
    --dataset datasets/1-0-0.csv \
    --output-dir runs/pawgrab --max-workers 24 --rerun
```

## Results (datasets/1-0-0.csv, 1,000 URLs, curl_cffi path)

| Config | Coverage | Avg F1 |
|---|---|---|
| Baseline (robots on) | 68.3% | 0.444 |
| robots off | 69.6% | 0.453 |
| + extractor candidate-scoring (recall) | 69.7% | 0.455 |
| + TLS-verify fallback (SSL/cert recovery) | **70.4%** | **0.461** |

Published baselines from scrape-evals: Firecrawl 80.9% / 0.68, Exa 76.3% / 0.53,
raw HTTP 50.6% / 0.36. Pawgrab runs self-hosted with no proxies or API keys.

## Where the ceiling is (measured, not assumed)

On the recall-limited successful pages, sampling shows the median page has only
**~56% of its `truth_text` present in the fetched HTML at all** — the rest is
JS-rendered. Of the recall gap: ~0.44 is JS-only content (needs rendering) and
~0.36 is content that *is* in the HTML but the extractors mislocate on non-article
(product / listing / FAQ / docs) layouts.

The browser fallback that would recover the JS half currently gets anti-bot 403s
(see `pawgrab_browser_scraper.py`), so the headline metric is gated by the
JS-fetch + anti-bot wall, not by a single tunable knob.

### Stealth curl→browser handoff — attempted, measured, infra-bound

Implemented and measured on the 121-page JS/anti-bot subset:

- **Cookie handoff** (`scrape_service.py`): forward cookies earned by the curl
  attempt (e.g. `cf_clearance`) into the browser re-fetch.
- **Escalation gate** (`fetcher.py`): only escalate Cloudflare-family challenges
  (browser-solvable); return the challenged result for reCAPTCHA / hCaptcha /
  DataDome / Sucuri instead of burning a browser slot and hardening the block.

Result: subset success stayed ~12%. The handoff can't help here because on these
hard pages curl never earned a clearance cookie (it received a JS shell), and
headless Chromium is fingerprint-blocked at the network layer (403) regardless of
cookies. **This wall is infrastructure — a CAPTCHA-solving service and/or
residential proxies plus a less-detectable browser — not a code knob.** The gate
and handoff are kept anyway: they're correct hygiene (they stop the browser from
making anti-bot pages *worse*, which the first browser run measured), just not a
score-mover on this dataset.

### Rendering + CF solver — implemented

The browser render path plus a Cloudflare/CAPTCHA solver are now wired end to end:

- **Bounded built-in Turnstile clicker** (`browser.solve_cloudflare(max_seconds=…)`):
  capped at 20 s/page instead of spinning ~90 s on "managed" challenges it can't
  clear. Budget-aware internally, so it degrades gracefully with no leaked futures.
- **External solver wired in** (`captcha_solver.solve_captcha_on_page`, previously
  orphaned): when `PAWGRAB_CAPTCHA_PROVIDER` + `PAWGRAB_CAPTCHA_API_KEY` are set
  (2captcha / capsolver), the fetch path routes Turnstile / reCAPTCHA / hCaptcha
  through the service and injects the token. No key → no-op, free path unchanged.
- **Solver-aware escalation**: CAPTCHA pages only escalate to a browser slot when a
  solver is configured; otherwise they return the challenged result instead of
  hardening into a 403.

Measured reality on this dataset: without an API key or residential proxies, the
hard Cloudflare-`managed` pages still 403 (datacenter IP + headless fingerprint is
served the hardest challenge tier) — but now they **fail in ~24 s instead of ~90 s**,
and the path to actually clear them is a config flip (`captcha_api_key`) rather than
missing code. Pure-JS (non-anti-bot) pages render and extract normally via the
browser path.

### The remaining code-side lever

- **Non-article extraction path** to capture the ~0.36 recall sitting in the HTML
  on product/listing/FAQ layouts — gate it behind expanded offline fixtures
  first so it can't regress the ~46% of pages already at F1 ≥ 0.8.
