# Anti-bot evasion

Pawgrab is built to fetch pages that actively try to block automated clients. This
page explains the stealth stack and how to **reproduce** its results yourself —
every number below comes from a harness you can run, not a marketing claim.

## The stack

Pawgrab layers several techniques, escalating only as far as a page requires:

1. **TLS fingerprint impersonation** — requests go out through `curl_cffi`
   impersonating a real browser's TLS/HTTP2 fingerprint (JA3/JA4), so the
   connection doesn't look like a Python HTTP library. A per-host identity is
   pinned and defaults Safari-first (most bot filters assume Chrome).
2. **Coherent fingerprint profiles** — when a headless browser is needed, every
   signal (user agent, GPU/WebGL renderer, screen, hardware concurrency, device
   memory, timezone, locale, TLS target) is drawn from a single seed and locked
   to one OS identity, so cross-checks stay consistent.
3. **Stealth browser patches** — ~40 Chromium launch flags plus a per-context
   evasion script patch `navigator.webdriver`, plugins, WebGL vendor/renderer,
   canvas/audio noise, permissions, and more.
4. **Humanized interaction** — optional realistic mouse paths, click holds, and
   per-character typing for behavioural scoring.
5. **Escalation ladder** — plain TLS fetch → retry with a different browser
   family on a challenge → headless browser → optional external CAPTCHA solver.

## Reproducible benchmark

`benchmarks/stealth.py` drives the exact fetch path the API uses against public
detection endpoints and scores the result. The judge functions are pure and unit
tested offline (`tests/test_benchmark.py`), so the scoring logic is verifiable
without the network; the live run needs outbound access.

```bash
pip install -e ".[dev]"
python -m benchmarks.stealth                                  # print a table
python -m benchmarks.stealth --json stealth.json              # + machine-readable
python -m benchmarks.stealth --markdown docs/anti-bot-results.md  # + this table
```

### Checks

| Check | What it proves | Scoring |
|-------|----------------|---------|
| `tls_echo` | The TLS/JA3 fingerprint echoed back is browser-like, not a library signature | pass/fail on fingerprint presence + non-library UA |
| `sannysoft` | Headless/webdriver property checks don't flag the browser | ratio of passed to failed result cells (pass ≥ 85%) |
| `incolumitas` | The behavioural scoring page is reachable without a hard block | reachability + challenge type (scores are client-side, not measured here) |

### Example output

The command writes a table like the one below. **Run it yourself to get current
numbers** — results depend on your network, proxies, and the detection sites,
which change over time, so no fixed figures are promised here.

```
| Check | Result | Score | Status | Browser | Challenge | Detail |
|-------|--------|------:|:------:|:-------:|:---------:|--------|
| tls_echo | ✅ pass | 100% | 200 | False | - | browser-like TLS fingerprint |
| sannysoft | ✅ pass | … | 200 | True | - | N/M checks passed |
| incolumitas | ✅ pass | — | 200 | True | - | reached scoring page |
```

The `tls_echo` check is the strongest single proof: a pass means Pawgrab's
outbound TLS handshake produces a genuine browser JA3/JA4 rather than the
fingerprint of a Python HTTP client.

!!! note
    This harness hits third-party public bot-test services and is **not** part of
    CI. Use it to validate a deployment and to track the stealth stack over time.
