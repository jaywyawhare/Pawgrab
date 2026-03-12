# API Reference

All endpoints are under `/v1` except `/health` and `/status`.

Set `PAWGRAB_API_KEY` to require Bearer token auth. Health and status endpoints skip auth.

---

## Error Responses

All errors across all endpoints return a consistent JSON shape:

```json
{
  "success": false,
  "error": "Human-readable error message",
  "code": "machine_readable_code",
  "details": "Additional context (optional)",
  "request_id": "a1b2c3d4e5f6"
}
```

### Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `validation_error` | 400, 422 | Invalid request parameters |
| `invalid_api_key` | 401 | Missing or wrong API key |
| `rate_limited` | 429 | API rate limit exceeded |
| `robots_blocked` | 403 | URL blocked by robots.txt |
| `resource_not_found` | 404 | Job or resource not found |
| `timeout` | 504 | Request timed out |
| `fetch_failed` | 502 | Failed to fetch the target URL |
| `browser_unavailable` | 503 | Browser pool not available |
| `queue_unavailable` | 503 | Redis/ARQ queue not available |
| `llm_unavailable` | 503 | OpenAI API key not configured |
| `extraction_failed` | 502 | Data extraction error |
| `search_failed` | 502 | Search provider error |
| `internal_error` | 500 | Unexpected server error |

### Response Headers

Every response includes these headers:

| Header | Example | Description |
|--------|---------|-------------|
| `X-Request-ID` | `a1b2c3d4e5f6` | Unique request identifier (send your own via `X-Request-ID` header) |
| `X-API-Version` | `0.0.4` | API version |
| `X-Response-Time` | `42.3ms` | Server-side request duration |
| `X-RateLimit-Limit` | `600` | Requests allowed per minute |
| `X-RateLimit-Remaining` | `598` | Requests remaining in current window |

### Rate Limiting

API-level rate limiting is applied per client (by API key or IP). Default: 600 requests/minute. Configurable via `PAWGRAB_API_RATE_LIMIT_RPM`.

When the limit is hit, the API returns:

- HTTP `429` with `code: "rate_limited"`
- `Retry-After: 60` header
- `X-RateLimit-Remaining: 0` header

Exempt paths: `/health`, `/status`, `/docs`, `/openapi.json`, `/redoc`.

---

## GET /health

```json
{
  "status": "ok",
  "version": "0.0.4",
  "checks": {
    "api": "ok",
    "redis": "ok",
    "browser_pool": "ok",
    "memory": "45.2%"
  }
}
```

Status levels:

- `ok` — all checks pass
- `degraded` — non-critical failure (e.g. browser pool unavailable)
- `unhealthy` — critical failure (Redis down)

## GET /status

```json
{ "status": "ok", "version": "0.0.4", "service": "pawgrab" }
```

---

## POST /v1/scrape

```bash
curl -X POST http://localhost:8000/v1/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com", "formats": ["markdown", "text"]}'
```

**Required:** `url`.

**Options:** `formats` (default `["markdown"]` - supports `markdown`, `html`, `text`, `json`, `csv`, `xml`), `wait_for_js` (`true`/`false`/`null` for auto), `timeout` (ms, default 30000), `include_metadata` (default true), `headers`, `cookies`.

**Content filtering:** `excluded_tags` (e.g. `["nav", "footer"]`), `excluded_selector`, `css_selector` (scope extraction), `word_count_threshold`, `content_filter` (`"pruning"` or `"bm25"`), `content_filter_query`, `citations` (links -> footnotes), `fit_markdown_query` + `fit_markdown_top_k` (BM25 section relevance).

**Captures (requires browser):** `screenshot`, `screenshot_fullpage`, `pdf`, `capture_network`, `capture_console`, `capture_mhtml`, `extract_media`, `capture_ssl`.

**Browser:** `browser_type` (`chromium`/`firefox`/`webkit`), `geolocation`, `text_mode` (skip images/CSS), `scroll_to_bottom`, `actions` (see below).

**Change tracking:** `monitor` + `monitor_ttl`.

### Page Actions

Array of sequential browser actions before extraction. Each has a `type`:

- `CLICK` - `selector`
- `TYPE` - `selector`, `text`
- `SCROLL` - `direction` (`up`/`down`), `amount` (px)
- `WAIT` - `amount` (ms)
- `WAIT_FOR` - `selector`
- `SCREENSHOT` - mid-action screenshot
- `EXECUTE_JS` - `text` (JS code)

### Response

```json
{
  "success": true,
  "url": "https://example.com",
  "warning": null,
  "metadata": { "title": "...", "description": "...", "language": "en", "url": "...", "status_code": 200, "word_count": 450 },
  "markdown": "...",
  "html": null,
  "text": null
}
```

Only requested formats/captures are populated. Also includes `json_data`, `csv_data`, `xml_data`, `screenshot_base64`, `pdf_base64`, `diff`, `network_requests`, `console_logs`, `mhtml_base64`, `media`, `ssl_certificate` - all null unless requested.

**Errors:** 403 `robots_blocked`, 502 `fetch_failed`, 503 `browser_unavailable`, 504 `timeout`.

---

## POST /v1/extract

```bash
curl -X POST http://localhost:8000/v1/extract \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com", "prompt": "Extract the main heading"}'
```

**Required:** `url`. `prompt` is required when `strategy` is `llm`.

**Options:** `strategy` (default `"llm"` - also `"css"`, `"xpath"`, `"regex"`), `schema_hint`, `json_schema` (strict structured output), `timeout`, `auto_schema`.

**LLM chunking:** `chunk_strategy` (`"fixed"`, `"sliding"`, `"semantic"`), `chunk_size`, `chunk_overlap`.

**Non-LLM:** `selectors` (CSS map), `xpath_queries` (XPath map), `patterns` (regex).

### Response

```json
{ "success": true, "url": "...", "data": { ... }, "auto_schema": null, "error": null }
```

**Errors:** 400 `validation_error` (missing prompt / bad config), 403 `robots_blocked`, 502 `extraction_failed`, 503 `llm_unavailable`, 504 `timeout`.

---

## POST /v1/crawl

Async - returns 202 with a job ID.

```bash
curl -X POST http://localhost:8000/v1/crawl \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: my-unique-key' \
  -d '{"url": "https://example.com", "max_pages": 20}'
```

**Required:** `url`.

**Options:** `max_pages` (default 10, max 500), `max_depth` (default 3, max 10), `formats`, `include_metadata`, `webhook_url`, `resume_job_id`, `strategy` (`"bfs"`, `"dfs"`, `"best_first"`), `allowed_domains`, `blocked_domains`, `include_path_patterns`, `exclude_path_patterns`, `keywords` (for best_first scoring).

**Idempotency:** Send `Idempotency-Key` header to safely retry. On duplicate key, the original response is returned with `X-Idempotency-Replay: true` header. Keys expire after 24 hours.

**Errors:** 400 `validation_error`, 404 `resource_not_found` (resume job), 503 `queue_unavailable`.

### GET /v1/crawl/{job_id}

Poll status. Query params: `page` (default 1), `limit` (default 50, max 200).

```json
{
  "job_id": "a1b2c3d4e5f6",
  "status": "completed",
  "pages_scraped": 5,
  "total_pages": 5,
  "results": [ ... ],
  "error": null,
  "page": 1,
  "limit": 50,
  "total_results": 5,
  "has_next": false
}
```

Status: `queued` -> `in_progress` -> `completed` | `failed`.

**Pagination:** `page` and `limit` control which slice of results is returned. `total_results` gives the total count (O(1) via Redis LLEN). `has_next` indicates whether more pages are available.

**Errors:** 400 `validation_error` (invalid job ID), 404 `resource_not_found`.

### GET /v1/crawl/{job_id}/stream

SSE stream. Events: `queued`, `in_progress`, `completed`, `failed`.

The stream emits SSE heartbeat comments (`: heartbeat`) every ~15 seconds when no real events arrive. This keeps the connection alive through reverse proxies (nginx, CloudFront, etc.) that may close idle connections.

**Errors:** 400 `validation_error`, 404 `resource_not_found`.

---

## POST /v1/batch/scrape

Async - returns 202 with a job ID.

```bash
curl -X POST http://localhost:8000/v1/batch/scrape \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: my-batch-key' \
  -d '{"urls": ["https://a.com", "https://b.com"]}'
```

**Required:** `urls` (1-100).

**Options:** `formats`, `include_metadata`, `wait_for_js`, `webhook_url`.

**Idempotency:** Same as `/v1/crawl` - send `Idempotency-Key` header for safe retries.

**Errors:** 503 `queue_unavailable`.

### GET /v1/batch/{job_id}

Same pagination as crawl (`page`, `limit`, `total_results`, `has_next`). Returns `urls_scraped`, `total_urls`, `results`.

**Errors:** 400 `validation_error`, 404 `resource_not_found`.

---

## POST /v1/search

Search the web, scrape each result in parallel (up to 5 concurrent).

```bash
curl -X POST http://localhost:8000/v1/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "python web scraping", "num_results": 5}'
```

**Required:** `query` (1-500 chars).

**Options:** `num_results` (default 5, max 10), `formats`, `include_metadata`.

Returns `results` (array of scrape responses), `total`, `failed_urls`.

**Errors:** 502 `search_failed`.

---

## POST /v1/map

Discover URLs from sitemap, falls back to homepage links.

**Required:** `url`.

**Options:** `include_subdomains` (default false), `limit` (default 5000, max 10000).

Returns `urls`, `total`, `source` (`"sitemap"` or `"crawl"`).

**Errors:** 502 `fetch_failed`.

---

## Proxy Pool

- **POST /v1/proxy/pool** - Add proxy. Body: `{"url": "http://user:pass@host:port"}`.
- **DELETE /v1/proxy/pool/{proxy_url}** - Remove (URL-encode the path). Errors: 404 `resource_not_found`.
- **GET /v1/proxy/pool** - List all.
- **GET /v1/proxy/pool/stats** - Pool stats.
