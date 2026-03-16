# Welcome to Pawgrab

Pawgrab is a professional-grade web scraping API that returns clean, structured content from any URL. Get results as Markdown, HTML, plain text, JSON, CSV, or XML.

## Why Pawgrab?

- **Anti-Bot Evasion** — TLS fingerprint impersonation via curl_cffi, stealth browser profiles, and automatic challenge detection
- **Smart JS Detection** — Starts fast with curl_cffi, automatically escalates to headless browser only when needed
- **Multiple Output Formats** — Markdown, HTML, text, JSON, CSV, XML
- **Async Crawling** — BFS, DFS, and BestFirst strategies with Redis job queue
- **LLM Extraction** — Extract structured data using OpenAI, CSS selectors, XPath, or regex
- **Production Ready** — Rate limiting, idempotency keys, proxy rotation, robots.txt compliance, Docker Compose deployment

## Quick Install

```bash
pip install pawgrab
patchright install chromium
```

## Quick Start

Start the API server:

```bash
# Start Redis (needed for /crawl and /batch)
docker run -d -p 6379:6379 redis:7-alpine

# Configure
cp .env.example .env

# Run the server
pawgrab serve
```

Make your first request:

```bash
curl -X POST http://localhost:8000/v1/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com"}'
```

## API Overview

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/scrape` | POST | Scrape a single URL |
| `/v1/crawl` | POST | Async site crawl (returns job ID) |
| `/v1/crawl/{job_id}` | GET | Poll crawl status with pagination |
| `/v1/crawl/{job_id}/stream` | GET | Real-time SSE stream |
| `/v1/extract` | POST | Structured data extraction |
| `/v1/batch/scrape` | POST | Batch scrape multiple URLs |
| `/v1/batch/{job_id}` | GET | Poll batch status |
| `/v1/search` | POST | Search the web and scrape results |
| `/v1/map` | POST | Discover URLs from sitemap |
| `/v1/proxy/pool` | POST/GET/DELETE | Manage proxy pool |
| `/health` | GET | Health check |
| `/status` | GET | Service info and version |

## Next Steps

- Read the [Quick Start](quickstart.md) guide for a complete setup walkthrough
- Explore the [API Reference](api.md) for all endpoints and options
- Learn about [Scraping](scraping.md), [Crawling](crawling.md), and [Extraction](extraction.md)
- Configure Pawgrab with [80+ environment variables](configuration.md)
