# Quick Start

Get up and running with Pawgrab in under 5 minutes.

## Installation

```bash
pip install pawgrab
patchright install chromium
```

## Option 1: CLI

The fastest way to try Pawgrab:

```bash
# Scrape a URL
pawgrab scrape https://example.com

# Scrape with JavaScript rendering
pawgrab scrape https://example.com --js

# Extract structured data with LLM
pawgrab extract https://example.com --prompt "Extract the main heading"

# Start the API server
pawgrab serve
```

## Option 2: Docker Compose

For production deployment with Redis (needed for crawl/batch jobs):

```bash
# Clone and configure
git clone https://github.com/jaywyawhare/Pawgrab.git
cd Pawgrab
cp .env.example .env

# Start everything
docker compose up
```

This starts three services:
- **API server** on port 8000
- **ARQ worker** for async crawl/batch jobs
- **Redis** for job queue, cache, and idempotency

## Option 3: Manual Setup

```bash
# Install
pip install pawgrab
patchright install chromium

# Start Redis (needed for /crawl and /batch)
docker run -d -p 6379:6379 redis:7-alpine

# Configure
cp .env.example .env

# Start the server
pawgrab serve
```

## Your First Scrape

Once the server is running, make your first API call:

```bash
curl -X POST http://localhost:8000/v1/scrape \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://news.ycombinator.com",
    "formats": ["markdown", "text"]
  }'
```

Or with Python:

```python
import requests

response = requests.post("http://localhost:8000/v1/scrape", json={
    "url": "https://news.ycombinator.com",
    "formats": ["markdown", "text"],
    "wait_for_js": True
})

data = response.json()
print(data["markdown"])
```

## Your First Crawl

Crawl an entire site asynchronously:

```bash
# Start a crawl job
curl -X POST http://localhost:8000/v1/crawl \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://docs.example.com",
    "max_pages": 20,
    "max_depth": 3,
    "formats": ["markdown"]
  }'

# Response: {"job_id": "crawl_abc123", "status": "running", ...}

# Poll for results
curl http://localhost:8000/v1/crawl/crawl_abc123
```

## Your First Extraction

Extract structured data using AI:

```bash
curl -X POST http://localhost:8000/v1/extract \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://example.com/products",
    "prompt": "Extract all products with name, price, and description",
    "strategy": "llm"
  }'
```

> **Note:** LLM extraction requires `PAWGRAB_OPENAI_API_KEY` to be set in your `.env` file.

## What's Next?

- [Scraping Guide](scraping.md) — Deep dive into scraping options
- [Crawling Guide](crawling.md) — Async crawling strategies
- [Extraction Guide](extraction.md) — LLM and non-LLM extraction
- [API Reference](api.md) — Complete endpoint documentation
- [Configuration](configuration.md) — All 80+ environment variables
