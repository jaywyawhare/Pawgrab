# Crawling Guide

Pawgrab supports async site crawling with multiple strategies, Redis-backed job queue, SSE streaming, and webhook notifications.

## Starting a Crawl

```bash
curl -X POST http://localhost:8000/v1/crawl \
  -H 'Content-Type: application/json' \
  -d '{
    "url": "https://docs.example.com",
    "max_pages": 50,
    "max_depth": 3,
    "formats": ["markdown"]
  }'
```

Response (HTTP 202):

```json
{
  "success": true,
  "job_id": "crawl_a1b2c3d4",
  "status": "running",
  "poll_url": "/v1/crawl/crawl_a1b2c3d4",
  "stream_url": "/v1/crawl/crawl_a1b2c3d4/stream"
}
```

## Crawl Strategies

### BFS (Breadth-First Search)

Default strategy. Crawls level by level — all links at depth 1 before depth 2.

```json
{"url": "https://example.com", "strategy": "bfs"}
```

Best for: Complete site coverage, sitemap generation.

### DFS (Depth-First Search)

Follows links deep before backtracking.

```json
{"url": "https://example.com", "strategy": "dfs"}
```

Best for: Deep content hierarchies, documentation sites.

### BestFirst

Prioritizes pages by keyword relevance scoring.

```json
{
  "url": "https://example.com",
  "strategy": "best_first",
  "keywords": ["python", "api", "tutorial"]
}
```

Best for: Targeted crawling, finding specific content.

## URL Filtering

Control which URLs get crawled:

```json
{
  "url": "https://example.com",
  "allowed_domains": ["example.com", "docs.example.com"],
  "blocked_domains": ["ads.example.com"],
  "include_path_patterns": ["/docs/*", "/blog/*"],
  "exclude_path_patterns": ["/admin/*", "/login"]
}
```

## Polling for Results

```bash
curl "http://localhost:8000/v1/crawl/crawl_a1b2c3d4?page=1&limit=50"
```

Response:

```json
{
  "job_id": "crawl_a1b2c3d4",
  "status": "completed",
  "pages_scraped": 42,
  "total_pages": 42,
  "results": [
    {"url": "https://example.com/page-1", "markdown": "...", "metadata": {...}},
    ...
  ],
  "page": 1,
  "limit": 50,
  "total_results": 42,
  "has_next": false
}
```

Status progression: `queued` → `in_progress` → `completed` | `failed`

## SSE Streaming

Stream results in real-time:

```bash
curl -N "http://localhost:8000/v1/crawl/crawl_a1b2c3d4/stream"
```

Events are emitted for each crawled page. Heartbeat comments (`: heartbeat`) are sent every ~15 seconds to keep the connection alive through reverse proxies.

## Idempotency

Safely retry crawl requests with an idempotency key:

```bash
curl -X POST http://localhost:8000/v1/crawl \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: my-unique-crawl-key' \
  -d '{"url": "https://example.com", "max_pages": 20}'
```

On duplicate key, the original response is returned with `X-Idempotency-Replay: true` header. Keys expire after 24 hours.

## Webhooks

Get notified when a crawl completes:

```json
{
  "url": "https://example.com",
  "max_pages": 100,
  "webhook_url": "https://your-api.com/crawl-complete"
}
```

## Crash Recovery

Crawl state is checkpointed to Redis every 10 pages. Use `resume_job_id` to continue a failed crawl:

```json
{
  "url": "https://example.com",
  "resume_job_id": "crawl_a1b2c3d4"
}
```

## Batch Scraping

Scrape multiple URLs in parallel:

```bash
curl -X POST http://localhost:8000/v1/batch/scrape \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: my-batch-key' \
  -d '{
    "urls": [
      "https://example.com/page-1",
      "https://example.com/page-2",
      "https://example.com/page-3"
    ],
    "formats": ["markdown"],
    "wait_for_js": true
  }'
```

Supports 1–100 URLs per batch. Poll results the same way as crawl jobs.

## Configuration

Key environment variables for crawling:

| Variable | Default | Description |
|----------|---------|-------------|
| `PAWGRAB_MAX_CRAWL_PAGES` | 500 | Maximum pages per crawl job |
| `PAWGRAB_MAX_CRAWL_DEPTH` | 10 | Maximum crawl depth |
| `PAWGRAB_WORKER_MAX_JOBS` | 5 | Concurrent worker jobs |
| `PAWGRAB_WORKER_JOB_TIMEOUT` | 600s | Job timeout |
| `PAWGRAB_CHECKPOINT_INTERVAL` | 10 | Pages between checkpoints |
| `PAWGRAB_REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
