<p align="center">
  <img src="https://raw.githubusercontent.com/jaywyawhare/Pawgrab/master/pawgrab.png" alt="Pawgrab" width="200">
</p>

<h1 align="center">Pawgrab</h1>

<p align="center">Web scraping API. Returns clean Markdown, HTML, text, or structured JSON from any URL.</p>


## Features

- Single URL scraping with multiple output formats
- Async site crawling (BFS, depth/page limits, Redis job queue)
- Structured extraction via OpenAI, CSS selectors, XPath, or regex
- Auto JS detection - curl_cffi first, Playwright fallback for JS-heavy pages
- Anti-bot evasion - TLS fingerprint impersonation, stealth browser profiles
- Robots.txt compliance
- Per-domain and API-level rate limiting
- Proxy rotation with health checking
- Unified error responses with machine-readable error codes
- SSE heartbeats for reliable streaming through reverse proxies
- Idempotency keys for safe retries on crawl/batch endpoints
- Request ID correlation and response timing headers
- Docker Compose deployment (API + worker + Redis)

## Install

```bash
pip install pawgrab
patchright install chromium
```

## Quickstart

```bash
# Start Redis (needed for /crawl)
docker run -d -p 6379:6379 redis:7-alpine

# Configure
cp .env.example .env
# Set PAWGRAB_OPENAI_API_KEY if you need /extract

# Run
pawgrab serve
```

Or with Docker:

```bash
cp .env.example .env
docker compose up
```

## API

All endpoints under `/v1`.

### POST /v1/scrape

```bash
curl -X POST http://localhost:8000/v1/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com"}'
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | string | required | URL to scrape |
| `formats` | array | `["markdown"]` | `markdown`, `html`, `text`, `json` |
| `wait_for_js` | bool/null | `null` | Force JS (`true`), skip (`false`), auto (`null`) |
| `timeout` | int | `30000` | Timeout in ms |

### POST /v1/crawl

Returns job ID (HTTP 202). Poll with `GET /v1/crawl/{job_id}`.

```bash
curl -X POST http://localhost:8000/v1/crawl \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com", "max_pages": 5}'
```

Supports `Idempotency-Key` header for safe retries.

### POST /v1/extract

Requires `PAWGRAB_OPENAI_API_KEY`.

```bash
curl -X POST http://localhost:8000/v1/extract \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com", "prompt": "Extract the main heading"}'
```

### POST /v1/search

Searches the web and scrapes each result in parallel.

```bash
curl -X POST http://localhost:8000/v1/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "python web scraping"}'
```

### GET /health

Returns `ok`, `degraded`, or `unhealthy` with per-component checks.

```bash
curl http://localhost:8000/health
```

### Error Responses

All errors return a consistent JSON shape:

```json
{
  "success": false,
  "error": "Human-readable message",
  "code": "machine_readable_code",
  "details": null,
  "request_id": "a1b2c3d4e5f6"
}
```

Error codes: `validation_error`, `invalid_api_key`, `rate_limited`, `robots_blocked`, `resource_not_found`, `timeout`, `fetch_failed`, `browser_unavailable`, `queue_unavailable`, `llm_unavailable`, `extraction_failed`, `search_failed`, `internal_error`.

### Response Headers

Every response includes:

| Header | Description |
|--------|-------------|
| `X-Request-ID` | Unique request identifier for correlation |
| `X-API-Version` | API version |
| `X-Response-Time` | Request duration (e.g. `42.3ms`) |
| `X-RateLimit-Limit` | Requests allowed per minute |
| `X-RateLimit-Remaining` | Requests remaining in current window |

## CLI

```bash
pawgrab scrape https://example.com
pawgrab scrape https://example.com --format text
pawgrab extract https://example.com --prompt "Extract the main heading"
pawgrab serve --port 8000 --reload
```

## Configuration

All settings via env vars with `PAWGRAB_` prefix. See [.env.example](.env.example) for the full list.

Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `PAWGRAB_API_KEY` | empty | API key for Bearer auth (empty = no auth) |
| `PAWGRAB_RATE_LIMIT_RPM` | `60` | Per-domain rate limit (requests/min) |
| `PAWGRAB_API_RATE_LIMIT_RPM` | `600` | API-level rate limit per client (requests/min) |
| `PAWGRAB_REDIS_URL` | `redis://localhost:6379/0` | Redis for job queue and idempotency |

## License

[DBaJ-GPL v69.420](LICENSE)
