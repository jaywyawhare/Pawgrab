# API Reference

All endpoints are under `/v1` except `/health` and `/status`.

Set `PAWGRAB_API_KEY` to require Bearer token auth. Health and status endpoints skip auth.

---

## GET /health

```json
{
  "status": "ok",
  "checks": { "api": "ok", "redis": "ok" }
}
```

`status` is `"degraded"` when Redis is down.

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

**Content filtering:** `excluded_tags` (e.g. `["nav", "footer"]`), `excluded_selector`, `css_selector` (scope extraction), `word_count_threshold`, `content_filter` (`"pruning"` or `"bm25"`), `content_filter_query`, `citations` (links → footnotes), `fit_markdown_query` + `fit_markdown_top_k` (BM25 section relevance).

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

**Errors:** 403 (robots.txt), 502 (fetch failed), 503 (browser pool unavailable).

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

**Errors:** 400 (missing prompt / bad config), 403 (robots.txt), 503 (OpenAI key not set).

---

## POST /v1/crawl

Async - returns 202 with a job ID.

```bash
curl -X POST http://localhost:8000/v1/crawl \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com", "max_pages": 20}'
```

**Required:** `url`.

**Options:** `max_pages` (default 10, max 500), `max_depth` (default 3, max 10), `formats`, `include_metadata`, `webhook_url`, `resume_job_id`, `strategy` (`"bfs"`, `"dfs"`, `"best_first"`), `allowed_domains`, `blocked_domains`, `include_path_patterns`, `exclude_path_patterns`, `keywords` (for best_first scoring).

### GET /v1/crawl/{job_id}

Poll status. Query params: `page` (default 1), `limit` (default 50, max 200).

```json
{
  "job_id": "a1b2c3d4e5f6",
  "status": "completed",
  "pages_scraped": 5,
  "total_pages": 5,
  "results": [ ... ],
  "error": null
}
```

Status: `queued` → `in_progress` → `completed` | `failed`.

### GET /v1/crawl/{job_id}/stream

SSE stream. Events: `queued`, `in_progress`, `completed`, `failed`.

---

## POST /v1/batch/scrape

Async - returns 202 with a job ID.

**Required:** `urls` (1–100).

**Options:** `formats`, `include_metadata`, `wait_for_js`, `webhook_url`.

### GET /v1/batch/{job_id}

Same pagination as crawl. Returns `urls_scraped`, `total_urls`, `results`.

---

## POST /v1/search

Search the web, scrape each result.

**Required:** `query` (1–500 chars).

**Options:** `num_results` (default 5, max 10), `formats`, `include_metadata`.

Returns `results` (array of scrape responses), `total`, `error`.

---

## POST /v1/map

Discover URLs from sitemap, falls back to homepage links.

**Required:** `url`.

**Options:** `include_subdomains` (default false), `limit` (default 5000, max 10000).

Returns `urls`, `total`, `source` (`"sitemap"` or `"crawl"`).

---

## Proxy Pool

- **POST /v1/proxy/pool** - Add proxy. Body: `{"url": "http://user:pass@host:port"}`.
- **DELETE /v1/proxy/pool/{proxy_url}** - Remove (URL-encode the path).
- **GET /v1/proxy/pool** - List all.
- **GET /v1/proxy/pool/stats** - Pool stats.
