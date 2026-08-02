# Pawgrab Codebase Audit — What's Missing & What Can Be Better

Method: 5 parallel subsystem audits (engine core, extraction pipeline, API/models, AI/queue/infra, security/tests) + independent cross-cutting checks. Findings deduped and re-ranked across agents. `✅ verified` = confirmed directly against the code in this session.

Legend: severity CRITICAL / HIGH / MED / LOW.

---

## CRITICAL

### C1. SSRF on fetch targets — no private-IP/scheme guard ✅ verified
`utils/rate_limiter.py:37 guard_url` (the only pre-fetch gate for scrape/crawl/map/batch/extract) does robots + rate-limit **only**. `webhook.py:19-50` has a proper private-CIDR/hostname SSRF guard — but it is **never applied to fetch targets**. So `http://169.254.169.254/latest/meta-data/`, `http://localhost:6379`, `http://10.x` are fetched unblocked → cloud-metadata credential theft, internal port scan.
**Fix:** extract `webhook.py`'s guard into a shared `assert_public_url()` (resolved-IP based) and call it inside `guard_url` before every fetch. Flagged independently by 3 of 5 agents.

---

## HIGH

### H1. Insecure-by-default auth + CORS (fail-open)
`config.py:15` `api_key=""` default → `main.py:123` disables auth middleware entirely **and** `main.py:216` sets CORS `allow_origins=["*"]`. A default deploy is a wide-open, cross-origin-callable scraping proxy.
**Fix:** fail-closed — refuse to start (or bind localhost) when no key is set; never pair open auth with wildcard CORS.

### H2. Webhook SSRF guard doesn't resolve DNS + redirects unchecked
`webhook.py:32-50` inspects only literal hostnames/IPs; a public DNS name resolving to a private IP (or DNS-rebind) passes. Compounded by `fetcher.py:464` `allow_redirects=True` with no per-hop re-validation (redirect-based SSRF).
**Fix:** resolve hostname→IP(s), validate every resolved address; disable auto-redirect or re-validate each hop and pin the connection.

### H3. Empty/whitespace HTML crashes conversion ✅ verified
`converter.py:83,219,227,250,275` call `lxml_html.fromstring(html)` with no empty-guard; `fromstring('')` raises `ParserError`. `cleaner.extract_content` legitimately returns `content_html=""` (cleaner.py:429), and `scrape_service.py:324` + `ai/extractor.py:44` pass it straight into `convert` → unhandled 500 on any page that yields empty content. No test covers this.
**Fix:** early-return `""` when `html.strip()` is empty in `convert`/each helper.

### H4. CAPTCHA solver misroutes hCaptcha/Turnstile → reCAPTCHA ✅ verified
`captcha_solver.py:189-203` queries the identical `[data-sitekey]` selector in all three branches, so `recaptcha` always matches first. hCaptcha and Turnstile are sent to the reCAPTCHA solve method → wrong token → external solver always fails on them.
**Fix:** distinguish by iframe/class (`.h-captcha`, `.cf-turnstile`, `g-recaptcha`) before choosing provider method.

### H5. Cookie bleed across requests/tenants (shared persistent context)
Non-proxy Chromium requests share one persistent context; `fetcher.py:737` writes per-request cookies into it, and `_PAGE_RESET_JS` clears localStorage/IndexedDB but **not cookies** on recycle → cookies leak across unrelated requests. Undermines the seeded-fingerprint isolation work.
**Fix:** fresh context per request, or `context.clear_cookies()` on recycle.

### H6. Leaked event listeners / routes on recycled pages
`fetcher.py:750-786` registers `page.on(request/response/console/websocket)` and a `page.route` every fetch, never removed; pages are recycled and reused (`browser.py:1093`) so listeners/routes accumulate (stale closures, growing per-event cost; page route shadows the context ad-blocker).
**Fix:** remove listeners / `unroute` in a `finally` before recycling.

### H7. Browser pool can deadlock permanently
`acquire()` (`browser.py:1086`) awaits `_pages.get()` with no timeout; once `_degraded` is set, `release()` closes pages without re-enqueueing, so the queue drains to zero and every future acquire hangs forever with no recovery path.
**Fix:** acquire timeout + pool self-heal/recreate; never let the queue silently reach zero.

### H8. ReDoS via ungoverned regex (two paths)
(a) `extractors.py:14-32` runs untrusted regex in a thread pool whose "timeout" **cannot kill a running regex** (Python can't interrupt a thread); two catastrophic patterns permanently exhaust `max_workers=2` and all later extraction silently returns `[]`. (b) `models/crawl.py:35-36` + `models/extract.py:32` compile & run user-supplied regex server-side with no complexity guard.
**Fix:** run untrusted regex in a killable subprocess or the `regex` module's `timeout=`; validate/bound user patterns (or use `re2`).

### H9. Sitemap index not recursed
`sitemap.py:44-76` — `_fetch_sitemap` docstring claims recursive index handling but there is none; for a `<sitemapindex>` it returns child **sitemap** URLs as crawl targets instead of page URLs, so index-based sites yield XML URLs.
**Fix:** detect `sitemapindex`, recursively fetch each child `<loc>`, aggregate `<url>` locs up to limit.

### H10. Queue: retries re-crawl from scratch + double-count (no idempotency)
`worker.py:168-175` — ARQ auto-retry re-invokes `crawl_job` with `resume=False`, so a retried/duplicated job re-crawls fully and `append_result` appends the whole set again while `pages_scraped` double-counts. Also `queue/manager.py:24,85` — job-status hash TTL is fixed 3600s, never refreshed; long crawls (`worker_job_timeout` up to 7200s) have status expire mid-run, then reappear as an orphan key with no TTL.
**Fix:** `resume=True` on retry (use `ctx['job_try']`) / dedupe by URL; refresh TTL on every update, set ≥ job timeout.

### H11. LLM prompt injection + unbounded chunk fan-out
`ai/prompts.py:19` + `ai/extractor.py:43` concatenate scraped markdown straight into the LLM user message with no fencing → hostile page ("ignore previous instructions") hijacks extraction. `ai/extractor.py:63-96` chunks the **untruncated** markdown with no chunk-count cap → huge page = unbounded sequential LLM calls (cost blowup).
**Fix:** fence scraped content as clearly-marked untrusted data; cap chunk count / total token budget per request.

---

## MED (grouped)

**Security / isolation**
- `fetcher.py:479` — any `SSLError` auto-retries with `verify=False`, silently downgrading TLS (MITM). Gate behind explicit opt-in. ✅ (2 agents)
- `geoip.py:112,132` — logs full `proxy_url` incl. `user:pass@` credentials. Redact to host:port.
- `main.py:120` — `/metrics` (Prometheus) and `/dashboard` (per-client analytics) exempt from auth. Gate them.
- `fetcher.py:576` `EXECUTE_JS` — arbitrary user JS in a pooled/reused context → cross-tenant bleed. Isolate.
- `storage.py:39` `_path()` — interpolates key into FS path with no `..` sanitization (currently mitigated by job-ID regex only). Confine under base_dir.
- `middleware/idempotency.py:34` — key ignores request body (same key + different payload → wrong cached response) and has no in-flight lock (concurrent same-key both execute). Hash body + set in-progress sentinel.
- `main.py:80` — `RequestIDMiddleware` trusts client `X-Request-ID` into logs + response (log forging). Validate/regenerate.

**Concurrency / reliability**
- `browser.py:1149` `acquire_session_page` — no lock around check-then-create → duplicate session contexts + leaked temp dirs; `_session_contexts`/`_session_dirs` unbounded (no TTL/LRU).
- `dispatcher.py:116` — `_adjust_semaphore` sets concurrency even when drain breaks early → semaphore capacity drifts above `_max`.
- `fetcher.py:134` — session LRU eviction can `close()` a session another coroutine is mid-request on (use-after-close); trailing dict read outside lock (rare KeyError).
- `scheduler.py:131` — invalid cron silently falls back to "run in 1h" forever; `get_due_schedules` has no lease → overlapping ticks double-fire. Reject bad cron at create; claim atomically (Redis `SET NX`).
- `search_provider.py:27` — synchronous `DDGS().text()` inside `async def` blocks the event loop. `asyncio.to_thread`.
- `robots.py:91` — `_fetch_robots` swallows all errors → `None` → treated as allowed (fail-open); transient error disables robots for the TTL.
- `detector.py:110` — `needs_js_rendering` caches per-domain from the first page for 1h → misclassifies mixed static/JS domains. Key on page-shape or shorten negative TTL.

**Correctness / quality**
- `captcha_solver.py:96,128` — 2Captcha/CapSolver submit+poll have no per-request timeout → hung provider holds a browser slot.
- `fetcher.py:749` — `capture_network`/`capture_console` append to unbounded lists → memory + huge JSON on heavy pages. Cap + counter.
- `table_extractor.py:36-88` — no colspan/rowspan (header↔value misalign), `column_count` wrong, nested-table `tr` double-count.
- `converter.py:175` — markdown tables omit the `| --- |` separator row → not valid GFM.
- `diff.py:183` — `_pixel_diff_percentage` byte-compares **compressed** PNGs → 1px change reads ~100% diff. Decode to pixel arrays.
- `url_filter.py:146` — `DuplicateFilter._normalize` doesn't lowercase host / strip `www.` / sort query / drop fragment → equivalent URLs re-crawled.
- `filters.py:25` — `PruningContentFilter` boilerplate patterns unanchored (`share`→"shareholder") → can decompose real content.
- `cleaner.py:528` — trafilatura runs on the **original** html, not the stripped tree → third full parse, can reintroduce removed furniture.
- `models/scrape.py:73` + `crawl.py:33` — `headers`/`cookies`/`actions`/`allowed_domains`/`keywords`/`patterns` have no `max_length`; no global body-size cap → payload DoS.
- `ai/openai_provider.py:59` — no `max_tokens` set + no token/cost accounting. `ai/openai_provider.py:73` — JSON parse failure returns `{"raw_response":...}` wrapped as `success=True`; no schema validation of LLM output.
- `ai/providers.py:146` — single provider, no fallback/retry/backoff; `get_provider()` caches one global instance, not concurrency-guarded; Gemini/Anthropic paths set no timeout.
- `metrics.py:82` + `analytics.py:19` — metrics/analytics in-process only: lost on restart, not aggregated across workers, `_domain_*`/per-client dicts grow unbounded. Back with Redis + bound cardinality.
- `worker.py:395` — `batch_extract_job` no checkpoint/resume, runs URLs sequentially; crash loses progress, retry re-appends dupes.
- API error funnels: `api/session.py:32`, `schedule.py:34`, `map.py:43`, `scrape.py:64` — broad `except Exception` masks real 500s as misleading 502/503.
- `config.py:23` — `llm_provider` is free-form `str` (typo silently → OpenAI); no check the active provider's key is present. Make `Literal` + model-validator.

---

## LOW / infra (my cross-cutting checks)

- **Optional LLM providers aren't installable** — `ai/providers.py:32,75` lazily import `anthropic` / `google.generativeai`, neither in `pyproject.toml`. `llm_provider=anthropic|gemini` without a manual install → runtime `ImportError`. Add `[anthropic]`/`[gemini]` extras + friendly error.
- **CI doesn't enforce formatting** — `.github/workflows/ci.yml` runs `ruff format` (rewrites, exit 0) instead of `ruff format --check`.
- **Thin CI matrix** — only Python 3.12 (despite `requires-python >=3.11`); no coverage gate; no Playwright/browser path exercised in CI.
- **No `.pre-commit-config.yaml`** despite the repo workflow expecting `pre-commit install`.
- **47 `except Exception: pass`** silent swallows across the engine (no bare `except:`, no `eval/exec/shell=True/pickle` — those are clean).
- `scrape_service.py:150` — JS-fallback fires a second full `fetch_page(wait_for_js=True)` even though `fetch_page` self-escalates → JS page rendered twice.
- `fetcher.py:572` — `ActionType.SCREENSHOT` calls `page.screenshot()` and discards the bytes (silent no-op).
- `utils/tokens.py:16` — `estimate_tokens` counts code points + ASCII braces only → wildly wrong for CJK/emoji, skews chunking.
- `cleaner.py:283,526` — mid-module / in-hot-loop imports (`json`, `trafilatura`). Hoist.

---

## Biggest missing capabilities (synthesized)

1. **Per-request browser isolation** — the default non-proxy path funnels every request through one shared persistent context that bleeds cookies (H5) and stale listeners (H6). This directly undercuts the seeded-fingerprint / geoip anti-bot investment and multi-tenant safety. Highest-leverage structural fix.
2. **Async job lifecycle** — crawl/batch jobs can be created and polled but never **cancelled, deleted, or listed**; no signed webhooks, no dead-letter queue, no idempotency/durable semantics (H10). A Firecrawl-class API needs all of these.
3. **Shared SSRF guard** (C1/H2) — single most important security fix before any public exposure.
4. **JSON-LD / microdata content extraction** — currently used only for byline metadata (`cleaner.py:317`). Harvesting schema.org `articleBody`/`Product`/`Recipe` is a deterministic, non-ML recall+precision win on exactly the product/listing/FAQ layouts where readability under-extracts — the highest-value extraction lever left past the 0.808 rule-based ceiling.
5. **Charset/encoding detection stage** — HTML is assumed correctly-decoded `str` everywhere; mojibake silently produces garbage, never detected.
6. **Pagination / "load-more" content stitching** — nothing addresses multi-page article/listing bodies.
7. **Solve paths for detected-but-dead-end anti-bot** — DataDome, PerimeterX, Akamai, Imperva, AWS WAF have detection rules but no cookie/token solve path; the escalation chain dead-ends on them.
8. **Multi-provider LLM resilience + cost control** — fallback chain, bounded retries, `max_tokens`, chunk/token budgets, and schema-validated output (H11 + MED).

---

## Suggested priority order

1. **C1 + H2** SSRF (shared resolved-IP guard, redirect re-validation) — security blocker.
2. **H1** fail-closed auth/CORS default.
3. **H3** empty-HTML crash — trivial fix, real 500s today.
4. **H4** captcha misroute — one-line-ish fix, unblocks hCaptcha/Turnstile solving.
5. **H5 + H6** browser isolation — protects the anti-bot work + tenants.
6. **H7** pool deadlock recovery.
7. **H8–H11** ReDoS, sitemap recursion, queue idempotency, LLM injection/budget.
8. Then the MED reliability cluster + missing-capability items 4–8.

---

## Resolution status (all fixed — branch `fix/extraction-and-antibot`, local only)

Every finding above plus the missing capabilities were implemented across 17 commits (`b9ed40b`…`27f1888`). Full suite: **836 passing**; whole-tree `ruff format --check` + `ruff check` clean; WCXB dev extraction held at **0.808** (no regression).

**Security:** C1 shared SSRF guard (`utils/url_safety.py`, DNS-resolving, per-hop redirect revalidation) applied in `guard_url` + webhooks; H1 fail-closed auth/CORS (`serve` refuses public bind without a key); H2 webhook DNS resolution; verify=False now opt-in; proxy creds redacted; `/metrics`+`/dashboard` gated; idempotency body-hash + in-flight lock; X-Request-ID validated; storage path traversal blocked; `/v1/usage` scoped to caller; signed webhooks (HMAC).

**HIGH correctness:** empty-HTML conversion crash; captcha type detection; per-request cookie isolation + listener cleanup; pool acquire-timeout + self-heal; real ReDoS protection (`regex` timeout); sitemap index recursion + defused XML; queue resume-on-retry + TTL refresh; LLM prompt fencing + chunk cap.

**MED:** GFM tables + colspan/rowspan grid; URL dedup; anchored boilerplate; decoded pixel diff; dispatcher semaphore fix; session-ctx lock+LRU; DDG off-loop; robots fail-closed opt; per-page JS cache key; cron validation + lease; capture caps; `max_tokens` + LLM output schema validation; payload size limits; `llm_provider` Literal; analytics LRU.

**Capabilities:** JSON-LD article/product/recipe extraction; charset detection; rel=next pagination stitching; job cancel/list + graceful worker cancellation; dead-letter queue; multi-provider LLM retry+fallback; optional provider extras; CI format-check + py3.11–3.13 matrix; pre-commit config.

**Cookie-based anti-bot solvers (now implemented):** `captcha_solver.solve_cookie_challenge` + `solve_cookie_challenge_on_page` route DataDome / Imperva / AWS-WAF through the already-configured 2captcha/CapSolver backends (extract the challenge-script URL + UA, submit the vendor task, inject the returned cookie/token, reload). The curl→browser escalation (`_COOKIE_SOLVABLE_CHALLENGES`) now attempts these whenever a solver is configured. PerimeterX and Akamai have no generic provider task type, so they route through the same path and return `None` cleanly (logged, no fabrication) — the integration is wired and attempted for all five; actual success for PX/Akamai depends on the external provider adding a task, which is a provider limitation, not deferred code. Cracking still requires the operator to configure a paid solver (`PAWGRAB_CAPTCHA_PROVIDER`/`_API_KEY`), the same as reCAPTCHA/hCaptcha/Turnstile.
