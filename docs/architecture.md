# Architecture

## Scrape Pipeline

`scrape_service.py` runs the full pipeline. Both `/v1/scrape` and the crawl worker use it.

1. robots.txt check (1h cache, 5min on failure)
2. Per-domain rate limit
3. Fetch with curl_cffi - random Safari/Chrome/Edge TLS fingerprint
4. If challenged -> retry with different browser family
5. If JS needed (auto-detected or `wait_for_js=true`) -> Patchright with stealth
6. Readability extraction
7. Optional pre/post filters: tag exclusion, CSS scoping, word count, pruning, BM25
8. Convert to requested formats
9. Optional captures: screenshot, PDF, network, console, MHTML, media, SSL, diff

## Fetcher Escalation

```
curl_cffi (Safari TLS) -> challenge? -> different family -> still blocked? -> Patchright
```

Challenge detection covers Cloudflare, reCAPTCHA, hCaptcha, Turnstile, AWS WAF, Akamai, Imperva, DataDome, PerimeterX, Sucuri.

Patchright stealth spoofs WebGL, canvas, audio, navigator, plugins, and WebRTC. Browser pool reuses contexts.

## Error Handling

All endpoints use `PawgrabError` exceptions with machine-readable `ErrorCode` values. The exception handler in `main.py` converts these to a unified `ErrorResponse` JSON shape:

```json
{
  "success": false,
  "error": "Human-readable message",
  "code": "error_code",
  "details": null,
  "request_id": "a1b2c3d4e5f6"
}
```

Request IDs are assigned by `RequestIDMiddleware` and propagated to error responses, logs, and the `X-Request-ID` response header for end-to-end correlation.

## Middleware Stack

Middleware executes from outermost to innermost on request, and innermost to outermost on response:

1. **RequestIDMiddleware** (outermost) — assigns `request_id`, measures response time, logs `request_completed` events, sets `X-Request-ID`, `X-API-Version`, `X-Response-Time` headers
2. **APIKeyMiddleware** — validates `Authorization: Bearer <key>` when `PAWGRAB_API_KEY` is set
3. **APIRateLimitMiddleware** — per-client rate limiting (by API key or IP), returns 429 with `Retry-After` header, sets `X-RateLimit-Limit` and `X-RateLimit-Remaining` headers
4. **IdempotencyMiddleware** (innermost) — caches responses for `POST /v1/crawl` and `POST /v1/batch/scrape` when `Idempotency-Key` header is present (24h TTL in Redis)

## Crawl

API creates a job in Redis and enqueues to ARQ. The worker:

1. Picks seed URL, initializes strategy (BFS/DFS/BestFirst)
2. Fetches page via the scrape pipeline
3. Extracts links, filters through `FilterChain` (domain, path, content type, dedup)
4. Adds new URLs to strategy queue
5. Checkpoints to Redis every 10 pages (crash recovery)
6. Publishes SSE events via Redis pub/sub
7. Fires webhook on completion

Max 5 concurrent jobs, 600s timeout each.

### SSE Streaming

The SSE endpoint (`GET /v1/crawl/{job_id}/stream`) uses Redis pub/sub with a polling loop instead of blocking `listen()`. When no real events arrive for 15 seconds, a heartbeat comment (`: heartbeat\n\n`) is emitted. This keeps connections alive through reverse proxies (nginx default timeout: 60s, CloudFront: 30s).

### Job Pagination

`GET /v1/crawl/{job_id}` and `GET /v1/batch/{job_id}` support `page` and `limit` query parameters. Responses include `total_results` (via Redis `LLEN`, O(1)) and `has_next` to indicate whether more pages are available.

## Search

The `/v1/search` endpoint scrapes search results in parallel using `asyncio.gather` with a `Semaphore(5)` to limit concurrency. This is significantly faster than sequential scraping - a 5-result search takes ~1x single scrape time instead of ~5x.

## Extract

LLM path: fetch -> clean -> markdown -> chunk (if large) -> OpenAI -> merge chunk results.

Non-LLM: fetch -> parse -> CSS/XPath/Regex extractor.

Chunking strategies: fixed-length (sentence boundaries), sliding window (overlapping), semantic (paragraph/heading boundaries).

## Proxy Pool

Configured via env vars or the `/v1/proxy` API at runtime. Rotation policies: round-robin, random, least-used. Health checks run at configurable intervals. Proxies are soft-evicted after N failures with backoff cooldown. Per-proxy metrics track success rate, EMA speed, and failure counts.

## Dependencies

- **fastapi, uvicorn** - HTTP server
- **pydantic-settings** - config
- **curl_cffi** - TLS impersonation
- **patchright, playwright-stealth** - browser rendering
- **readability-lxml** - content extraction
- **beautifulsoup4, lxml** - HTML parsing
- **openai** - LLM calls
- **arq, redis** - job queue
- **protego** - robots.txt
- **aiolimiter** - rate limiting (per-domain and API-level)
- **typer** - CLI
- **structlog** - structured logging
- **duckduckgo-search** - web search
- **pymupdf** - PDF text
- **orjson** - fast JSON serialization
