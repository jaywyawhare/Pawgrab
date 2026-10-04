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
| `X-API-Version` | `0.1.0` | API version |
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
  "version": "0.1.0",
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
{ "status": "ok", "version": "0.1.0", "service": "pawgrab" }
```

## GET /health/capabilities

Per-capability readiness given the current configuration (distinct from `/health`, which checks infra liveness). Each capability reports `ok` (provably usable), `warn` (configured but unverifiable, or a selected backend is misconfigured), or `off` (optional and absent). Also available from the CLI: `pawgrab doctor [--json]`.

```json
{
  "status": "ok",
  "summary": { "ok": 5, "warn": 0, "off": 2 },
  "capabilities": {
    "fetch": { "status": "ok", "message": "HTTP fetch via curl_cffi TLS impersonation" },
    "browser": { "status": "ok", "message": "browser pool running" },
    "llm": { "status": "ok", "message": "openai key configured" },
    "captcha": { "status": "off", "message": "no captcha solver configured (optional)" },
    "proxies": { "status": "off", "message": "no proxies configured (optional)" },
    "search": { "status": "ok", "message": "keyless meta-search (duckduckgo)" },
    "storage": { "status": "ok", "message": "local filesystem (./pawgrab_data)" }
  }
}
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

**LLM enrichment (requires LLM provider, one shared LLM call):** `summary: true` adds a TL;DR to `summary`; `question` adds a grounded answer to `answer`; `highlights: true` extracts verbatim key excerpts into `highlights`.

**Selector healing:** if `css_selector` matches nothing (the site changed its markup), progressively relaxed variants of the selector are tried — pseudo-classes stripped first, then the individual class/id tokens, then the bare tag.

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

**Options:** `num_results` (default 5, max 10), `formats`, `include_metadata`, `include_domains` / `exclude_domains` (domain scoping, subdomains included, e.g. `exclude_domains: ["pinterest.com"]`), `scrape` (false = SERP metadata only), plus search controls: `page`, `time_range`, `safesearch`, `region`, `category`.

Returns `results` (array of scrape responses), `total`, `failed_urls`.

**Errors:** 502 `search_failed`.

---

## POST /v1/parse

Run raw HTML through the extraction pipeline without fetching — content cleaning, selector scoping, and format conversion, identical to `/v1/scrape` post-processing.

```bash
curl -X POST http://localhost:8000/v1/parse \
  -H 'Content-Type: application/json' \
  -d '{"html": "<html><body><article><h1>Title</h1></article></body></html>", "formats": ["markdown"]}'
```

**Required:** `html` (up to 5 MB).

**Options:** `url` (source URL for metadata), `formats`, `css_selector`, `excluded_tags`, `excluded_selector`, `word_count_threshold`, `content_filter`, `content_filter_query`.

Returns `success`, `markdown`/`html`/`text`/`json_data`/`csv_data`/`xml_data` (per requested format), `title`.

---

## POST /v1/transcript

Extract a YouTube video's caption track as structured, timestamped segments — reads the published captions directly (no audio download or speech-to-text).

```bash
curl -X POST http://localhost:8000/v1/transcript \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://youtu.be/dQw4w9WgXcQ", "languages": ["en"]}'
```

**Required:** `url` (watch, shorts, embed, or youtu.be).

**Options:** `languages` (preferred caption language codes in priority order).

Returns `success`, `video_id`, `title`, `language`, `auto_generated`, `segments` (`[{start, duration, text}]`), `text` (joined). When the video has no captions, returns `success: false` with `error`.

---

## POST /v1/feed

Parse an RSS 2.0 or Atom feed into structured items.

```bash
curl -X POST http://localhost:8000/v1/feed \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com/feed.xml", "limit": 50}'
```

**Required:** `url`.

**Options:** `limit` (default 50, max 500).

Returns `success`, `type` (`rss`/`atom`), `title`, `link`, `description`, `items` (`[{title, link, published, summary, id, author}]`), `count`.

---

## POST /v1/reddit

Read a Reddit post (with a bounded comment tree) or a subreddit/listing's posts via the public `.json` endpoint — no login or API key.

```bash
curl -X POST http://localhost:8000/v1/reddit \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://www.reddit.com/r/python/comments/abc/some_title/"}'
```

**Required:** `url` (post, subreddit, or listing).

**Options:** `limit` (posts for a listing URL, default 50, max 100).

Returns `success`, `kind` (`post`/`listing`), and either `post` + `comments` (nested `[{author, body, score, created_utc, replies}]`) or `posts`.

---

## POST /v1/github

Read GitHub repository metadata via the public REST API — no token (unauthenticated rate limit applies).

```bash
curl -X POST http://localhost:8000/v1/github \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://github.com/psf/requests"}'
```

**Required:** `url` (`github.com/owner/repo`).

Returns `success`, `full_name`, `description`, `owner`, `stars`, `forks`, `watchers`, `open_issues`, `language`, `topics`, `license`, `default_branch`, `homepage`, `archived`, and `created_at`/`updated_at`/`pushed_at`.

---

## POST /v1/read

Auto-detect the URL's platform and route to the best reader: YouTube videos → transcript, Reddit → post/listing, GitHub repos → metadata, RSS/Atom feeds → feed items, everything else → a web scrape.

```bash
curl -X POST http://localhost:8000/v1/read \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://youtu.be/dQw4w9WgXcQ"}'
```

**Required:** `url`.

**Options:** `languages` (used when the URL is a video), `limit` (feed items), `formats` (used on the web-scrape fallback).

Returns `success`, `kind` (`youtube`/`reddit`/`github`/`feed`/`web`), `url`, and whichever of `transcript`/`reddit`/`github`/`feed`/`scrape` applies.

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
