<p align="center">
  <img src="https://raw.githubusercontent.com/jaywyawhare/Pawgrab/master/pawgrab.png" alt="Pawgrab" width="200">
</p>

<h1 align="center">Pawgrab</h1>

<p align="center">Web scraping API. Returns clean Markdown, HTML, text, or structured JSON from any URL.</p>


## Features

- Single URL scraping with multiple output formats
- Async site crawling (BFS, depth/page limits, Redis job queue)
- Structured extraction via OpenAI, CSS selectors, XPath, or regex
- Auto JS detection — curl_cffi first, Playwright fallback for JS-heavy pages
- Anti-bot evasion — TLS fingerprint impersonation, stealth browser profiles
- Robots.txt compliance
- Per-domain rate limiting
- Proxy rotation with health checking
- Docker Compose deployment (API + worker + Redis)

## Quickstart

```bash
pip install -e ".[dev]"
playwright install chromium

# Redis (needed for /crawl)
docker run -d -p 6379:6379 redis:7-alpine

cp .env.example .env
# Set PAWGRAB_OPENAI_API_KEY if you need /extract

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

### POST /v1/extract

Requires `PAWGRAB_OPENAI_API_KEY`.

```bash
curl -X POST http://localhost:8000/v1/extract \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com", "prompt": "Extract the main heading"}'
```

### GET /health

```bash
curl http://localhost:8000/health
```

## CLI

```bash
pawgrab scrape https://example.com
pawgrab scrape https://example.com --format text
pawgrab extract https://example.com --prompt "Extract the main heading"
pawgrab serve --port 8000 --reload
```

## Configuration

All settings via env vars with `PAWGRAB_` prefix. See [.env.example](.env.example) for the full list.

## License

[DBaJ-GPL v69.420](LICENSE)
