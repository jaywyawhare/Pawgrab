# API Reference

All endpoints are under `/v1` except `/health` and `/status`.

Set `PAWGRAB_API_KEY` to require Bearer token auth. Health and status endpoints skip auth.

## Error Responses

All errors return a consistent JSON shape:

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

Every response includes:

| Header | Example | Description |
|--------|---------|-------------|
| `X-Request-ID` | `a1b2c3d4e5f6` | Unique request identifier |
| `X-API-Version` | `0.1.0` | API version |
| `X-Response-Time` | `42.3ms` | Server-side request duration |
| `X-RateLimit-Limit` | `600` | Requests allowed per minute |
| `X-RateLimit-Remaining` | `598` | Requests remaining |

### Rate Limiting

API-level rate limiting per client (by API key or IP). Default: 600 requests/minute.

When the limit is hit:
- HTTP `429` with `code: "rate_limited"`
- `Retry-After: 60` header
- `X-RateLimit-Remaining: 0` header

Exempt paths: `/health`, `/status`, `/docs`, `/openapi.json`, `/redoc`.

## GET /health

```json
{
  "status": "ok",
  "version": "0.1.0",
  "checks": {
    "api": "ok",
    "redis": "ok",
    "browser_pool": "ok",
    "memory": "45.2%"
  }
}
```

Status levels: `ok`, `degraded` (non-critical failure), `unhealthy` (critical failure).

## GET /status

```json
{"status": "ok", "version": "0.1.0", "service": "pawgrab"}
```

## POST /v1/scrape

Scrape a single URL and return clean content.

```bash
curl -X POST http://localhost:8000/v1/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com", "formats": ["markdown", "text"]}'
```

### Parameters

**Required:** `url`

**Output:** `formats` (default `["markdown"]`) — supports `markdown`, `html`, `text`, `json`, `csv`, `xml`

**Browser:** `wait_for_js` (`true`/`false`/`null` for auto), `timeout` (ms, default 30000), `browser_type` (`chromium`/`firefox`/`webkit`), `text_mode`, `scroll_to_bottom`, `geolocation`

**Filtering:** `excluded_tags`, `excluded_selector`, `css_selector`, `word_count_threshold`, `content_filter` (`"pruning"` or `"bm25"`), `content_filter_query`, `citations`, `fit_markdown_query`, `fit_markdown_top_k`

**Captures:** `screenshot`, `screenshot_fullpage`, `pdf`, `capture_network`, `capture_console`, `capture_mhtml`, `extract_media`, `capture_ssl`

**Other:** `headers`, `cookies`, `include_metadata`, `monitor`, `monitor_ttl`, `actions` (page actions array)

### Page Actions

Array of sequential browser actions. Each has a `type`:

| Type | Parameters | Description |
|------|-----------|-------------|
| `CLICK` | `selector` | Click an element |
| `TYPE` | `selector`, `text` | Type into an input |
| `SCROLL` | `direction`, `amount` | Scroll up/down (px) |
| `WAIT` | `amount` | Wait (ms) |
| `WAIT_FOR` | `selector` | Wait for element |
| `SCREENSHOT` | — | Mid-action screenshot |
| `EXECUTE_JS` | `text` | Run JavaScript |

### Response

```json
{
  "success": true,
  "url": "https://example.com",
  "warning": null,
  "metadata": {"title": "...", "description": "...", "language": "en", "status_code": 200, "word_count": 450},
  "markdown": "...",
  "html": null,
  "text": null,
  "screenshot_base64": null,
  "pdf_base64": null,
  "diff": null
}
```

## POST /v1/extract

Extract structured data from a URL.

```bash
curl -X POST http://localhost:8000/v1/extract \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com", "prompt": "Extract the main heading"}'
```

### Parameters

**Required:** `url`. `prompt` required when `strategy` is `llm`.

**Strategy:** `strategy` (default `"llm"`) — also `"css"`, `"xpath"`, `"regex"`

**LLM:** `schema_hint`, `json_schema`, `auto_schema`, `chunk_strategy` (`"fixed"`, `"sliding"`, `"semantic"`), `chunk_size`, `chunk_overlap`

**Non-LLM:** `selectors` (CSS map), `xpath_queries` (XPath map), `patterns` (regex map)

### Response

```json
{"success": true, "url": "...", "data": {...}, "auto_schema": null, "error": null}
```

## POST /v1/crawl

Async crawl — returns HTTP 202 with job ID.

```bash
curl -X POST http://localhost:8000/v1/crawl \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: my-unique-key' \
  -d '{"url": "https://example.com", "max_pages": 20}'
```

### Parameters

**Required:** `url`

**Crawl:** `max_pages` (default 10, max 500), `max_depth` (default 3, max 10), `strategy` (`"bfs"`, `"dfs"`, `"best_first"`), `keywords` (for best_first)

**Filtering:** `allowed_domains`, `blocked_domains`, `include_path_patterns`, `exclude_path_patterns`

**Other:** `formats`, `include_metadata`, `webhook_url`, `resume_job_id`

**Idempotency:** Send `Idempotency-Key` header for safe retries (24h TTL).

### GET /v1/crawl/{job_id}

Poll status. Query params: `page` (default 1), `limit` (default 50, max 200).

```json
{
  "job_id": "a1b2c3d4e5f6",
  "status": "completed",
  "pages_scraped": 5,
  "total_pages": 5,
  "results": [...],
  "page": 1,
  "limit": 50,
  "total_results": 5,
  "has_next": false
}
```

### GET /v1/crawl/{job_id}/stream

SSE stream with heartbeat comments every ~15 seconds.

## POST /v1/batch/scrape

Async batch scrape — returns HTTP 202.

```bash
curl -X POST http://localhost:8000/v1/batch/scrape \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: my-batch-key' \
  -d '{"urls": ["https://a.com", "https://b.com"]}'
```

**Required:** `urls` (1–100). **Options:** `formats`, `include_metadata`, `wait_for_js`, `webhook_url`.

### GET /v1/batch/{job_id}

Same pagination as crawl. Returns `urls_scraped`, `total_urls`, `results`.

## POST /v1/search

Search the web and scrape each result in parallel.

```bash
curl -X POST http://localhost:8000/v1/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "python web scraping", "num_results": 5}'
```

**Required:** `query` (1–500 chars). **Options:** `num_results` (default 5, max 10), `formats`, `include_metadata`.

Returns `results` array, `total`, `failed_urls`.

## POST /v1/map

Discover URLs from sitemap (falls back to homepage links).

**Required:** `url`. **Options:** `include_subdomains` (default false), `limit` (default 5000, max 10000).

Returns `urls`, `total`, `source` (`"sitemap"` or `"crawl"`).

## Proxy Pool

- **POST /v1/proxy/pool** — Add proxy: `{"url": "http://user:pass@host:port"}`
- **DELETE /v1/proxy/pool/{proxy_url}** — Remove proxy (URL-encode the path)
- **GET /v1/proxy/pool** — List all proxies
- **GET /v1/proxy/pool/stats** — Pool statistics
