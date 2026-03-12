---
hide:
  - navigation
  - toc
---

<div class="hero" markdown>

# Pawgrab

### Web scraping API. Returns clean Markdown, HTML, text, or structured JSON from any URL.

[Get Started](#install){ .md-button .md-button--primary }
[API Reference](api.md){ .md-button }

</div>

---

## Features

<div class="grid cards" markdown>

-   **Multiple Output Formats**

    ---

    Get results as Markdown, HTML, plain text, JSON, CSV, or XML

-   **Async Crawling**

    ---

    BFS/DFS/BestFirst strategies with depth and page limits via Redis job queue

-   **AI Extraction**

    ---

    Structured data extraction via OpenAI, CSS selectors, XPath, or regex

-   **Smart JS Detection**

    ---

    curl_cffi first, automatic Patchright fallback for JS-heavy pages

-   **Anti-Bot Evasion**

    ---

    TLS fingerprint impersonation and stealth browser profiles

-   **Production Ready**

    ---

    Unified error responses, API rate limiting, request ID correlation, response timing, SSE heartbeats, idempotency keys, proxy rotation, robots.txt compliance, Docker Compose deployment

</div>

---

## Install

```bash
pip install pawgrab
patchright install chromium
```

## Quickstart

=== "CLI"

    ```bash
    # Start Redis (needed for /crawl)
    docker run -d -p 6379:6379 redis:7-alpine

    # Configure
    cp .env.example .env

    # Run
    pawgrab serve
    ```

=== "Docker"

    ```bash
    cp .env.example .env
    docker compose up
    ```

=== "curl"

    ```bash
    curl -X POST http://localhost:8000/v1/scrape \
      -H 'Content-Type: application/json' \
      -d '{"url": "https://example.com"}'
    ```

---

## Quick API Overview

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/scrape` | POST | Scrape a single URL |
| `/v1/crawl` | POST | Async site crawl (returns job ID) |
| `/v1/crawl/{job_id}` | GET | Poll crawl status with pagination |
| `/v1/crawl/{job_id}/stream` | GET | Real-time SSE stream with heartbeats |
| `/v1/extract` | POST | Structured data extraction |
| `/v1/batch/scrape` | POST | Batch scrape multiple URLs |
| `/v1/batch/{job_id}` | GET | Poll batch status with pagination |
| `/v1/search` | POST | Search the web and scrape results (parallel) |
| `/v1/map` | POST | Discover URLs from sitemap |
| `/v1/proxy/pool` | POST/GET | Manage proxy pool |
| `/health` | GET | Health check (API, Redis, browser pool, memory) |
| `/status` | GET | Service info and version |

[Full API Reference](api.md){ .md-button }

---

## License

[DBaJ-GPL v69.420](https://github.com/jaywyawhare/Pawgrab/blob/master/LICENSE)
