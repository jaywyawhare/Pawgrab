# Reliability

## The fetch-escalation ladder

Pawgrab tries the cheapest fetch tier first and escalates only when a page resists:

1. **curl_cffi** — HTTP with browser TLS fingerprint impersonation. Fast, no browser.
2. **stealth browser** — Patchright/Chromium with the stealth profile, for JS-heavy
   or lightly protected pages.
3. **proxy browser** — the stealth browser routed through a rotating proxy, for
   pages that block the datacenter IP.

Each tier is counted in metrics (`pawgrab_fetch_tier_curl|browser|proxy`), so you can
see how often escalation happens and where latency comes from (`/metrics` for the
Prometheus text, or the `fetch_tiers` block in `/metrics.json`).

## Measuring coverage and latency

Don't claim coverage — measure it. The benchmark runner reports coverage and
P50/P95 latency over a URL list, broken down by tier:

```bash
python -m benchmarks.coverage urls.txt
```

```json
{
  "urls": 50,
  "coverage": 0.94,
  "p50_s": 1.2,
  "p95_s": 3.6,
  "tiers": { "curl": 38, "browser": 9, "proxy": 3 }
}
```

Publish the numbers this prints for your own URL set and proxy configuration, not a
marketing figure. Coverage and latency depend heavily on your proxies and the sites
you target.
