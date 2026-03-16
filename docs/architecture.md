# Architecture

## Scrape Pipeline

`scrape_service.py` runs the full pipeline. Both `/v1/scrape` and the crawl worker use it.

1. **robots.txt check** — 1h cache, 5min on failure
2. **Per-domain rate limit** — Configurable RPM per domain
3. **Fetch with curl_cffi** — Random Safari/Chrome/Edge TLS fingerprint
4. **Challenge detection** — If challenged, retry with different browser family
5. **JS escalation** — If JS needed (auto-detected or `wait_for_js=true`), use Patchright with stealth
6. **Readability extraction** — Extract main content
7. **Content filtering** — Tag exclusion, CSS scoping, word count, pruning, BM25
8. **Format conversion** — Convert to requested output formats
9. **Optional captures** — Screenshot, PDF, network, console, MHTML, media, SSL, diff

## Fetcher Escalation

```
curl_cffi (Safari TLS) → challenge? → different family → still blocked? → Patchright
```

Challenge detection covers: Cloudflare, reCAPTCHA, hCaptcha, Turnstile, AWS WAF, Akamai, Imperva, DataDome, PerimeterX, Sucuri.

Patchright stealth spoofs WebGL, canvas, audio, navigator, plugins, and WebRTC. Browser pool reuses contexts for efficiency.

## Middleware Stack

Middleware executes outermost → innermost on request, innermost → outermost on response:

1. **RequestIDMiddleware** (outermost) — Assigns `request_id`, measures response time, logs events, sets `X-Request-ID`, `X-API-Version`, `X-Response-Time` headers
2. **APIKeyMiddleware** — Validates `Authorization: Bearer <key>` when `PAWGRAB_API_KEY` is set
3. **APIRateLimitMiddleware** — Per-client rate limiting (by API key or IP), returns 429 with `Retry-After`
4. **IdempotencyMiddleware** (innermost) — Caches responses for POST crawl/batch with `Idempotency-Key` header (24h TTL)

Additional middleware:
- **GZipMiddleware** — Response compression (>1000 bytes)
- **CORSMiddleware** — CORS headers (open when no auth, restricted when auth enabled)

## Error Handling

All endpoints use `PawgrabError` exceptions with machine-readable `ErrorCode` values. The exception handler converts these to unified `ErrorResponse` JSON:

```json
{
  "success": false,
  "error": "Human-readable message",
  "code": "error_code",
  "details": null,
  "request_id": "a1b2c3d4e5f6"
}
```

Request IDs propagate to error responses, logs, and `X-Request-ID` header for end-to-end correlation.

## Crawl Architecture

The crawl system uses Redis and ARQ for async job processing:

1. API creates job in Redis, enqueues to ARQ
2. Worker picks seed URL, initializes strategy (BFS/DFS/BestFirst)
3. Fetches page via the scrape pipeline
4. Extracts links, filters through `FilterChain` (domain, path, content type, dedup)
5. Adds new URLs to strategy queue
6. Checkpoints to Redis every 10 pages (crash recovery)
7. Publishes SSE events via Redis pub/sub
8. Fires webhook on completion

### SSE Streaming

Redis pub/sub with a polling loop. Heartbeat comments (`: heartbeat`) every ~15 seconds keep connections alive through reverse proxies.

### Job Pagination

`GET /v1/crawl/{job_id}` and `GET /v1/batch/{job_id}` support `page`/`limit` params. `total_results` uses Redis `LLEN` (O(1)).

## Search Architecture

`/v1/search` scrapes results in parallel using `asyncio.gather` with `Semaphore(5)`. A 5-result search takes ~1x single scrape time instead of ~5x sequential.

## Extract Architecture

### LLM Path
fetch → clean → markdown → chunk (if large) → OpenAI → merge results

### Non-LLM Path
fetch → parse → CSS/XPath/Regex extractor

### Chunking
- **Fixed** — Sentence boundary splits
- **Sliding** — Overlapping windows
- **Semantic** — Paragraph/heading boundary splits

## Proxy Pool

Configured via env vars or `/v1/proxy` API at runtime. Features:
- Rotation policies: round-robin, random, least-used
- Health checks at configurable intervals
- Soft-eviction after N failures with backoff cooldown
- Per-proxy metrics: success rate, EMA speed, failure counts

## Dependencies

| Package | Purpose |
|---------|---------|
| **fastapi, uvicorn** | HTTP server |
| **pydantic-settings** | Configuration management |
| **curl_cffi** | TLS fingerprint impersonation |
| **patchright, playwright-stealth** | Browser rendering + stealth |
| **readability-lxml** | Content extraction |
| **beautifulsoup4, lxml** | HTML parsing |
| **openai** | LLM extraction |
| **arq, redis** | Job queue |
| **protego** | robots.txt parsing |
| **aiolimiter** | Rate limiting |
| **typer** | CLI framework |
| **structlog** | Structured logging |
| **duckduckgo-search** | Web search |
| **pymupdf** | PDF text extraction |
| **orjson** | Fast JSON serialization |
