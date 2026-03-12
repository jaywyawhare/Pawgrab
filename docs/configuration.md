# Configuration

Env vars with `PAWGRAB_` prefix. See `.env.example`.

## Server

- `PAWGRAB_HOST` - default `0.0.0.0`
- `PAWGRAB_PORT` - default `8000`
- `PAWGRAB_LOG_LEVEL` - default `info`
- `PAWGRAB_API_KEY` - empty = no auth

## Redis

- `PAWGRAB_REDIS_URL` - default `redis://localhost:6379/0`. Needed for crawl, batch, health, idempotency cache.

## OpenAI

- `PAWGRAB_OPENAI_API_KEY` - needed for `/v1/extract` with LLM strategy
- `PAWGRAB_OPENAI_MODEL` - default `gpt-4o-mini`

## Browser

- `PAWGRAB_BROWSER_POOL_SIZE` - default `3` (Playwright instances)
- `PAWGRAB_BROWSER_TIMEOUT` - default `30000` ms
- `PAWGRAB_BROWSER_TYPE` - `chromium`, `firefox`, or `webkit` (default `chromium`)
- `PAWGRAB_STEALTH_MODE` - default `true` (fingerprint evasion)
- `PAWGRAB_MAX_CHALLENGE_RETRIES` - default `2`
- `PAWGRAB_IMPERSONATE` - curl_cffi target e.g. `chrome124`, empty = random

## Rate Limiting

- `PAWGRAB_RATE_LIMIT_RPM` - default `60`, per domain (applied during scraping)
- `PAWGRAB_API_RATE_LIMIT_RPM` - default `600`, API-level per client (by API key or IP). Applies to all endpoints except `/health`, `/status`, `/docs`, `/openapi.json`, `/redoc`. Returns `429` with `Retry-After` header when exceeded.
- `PAWGRAB_RESPECT_ROBOTS` - default `true`

## Proxy

- `PAWGRAB_PROXY_URL` - single proxy
- `PAWGRAB_PROXY_URLS` - comma-separated list for rotation
- `PAWGRAB_PROXY_ROTATION_POLICY` - `round_robin`, `random`, or `least_used`
- `PAWGRAB_PROXY_HEALTH_CHECK` - default `true`
- `PAWGRAB_PROXY_HEALTH_CHECK_INTERVAL` - default `300` seconds
- `PAWGRAB_PROXY_OFFER_LIMIT` - default `25`, skip proxy after N consecutive offers
- `PAWGRAB_PROXY_EVICT_AFTER_FAILURES` - default `3`
- `PAWGRAB_PROXY_BACKOFF_SECONDS` - default `60`

## Search

- `PAWGRAB_SEARCH_PROVIDER` - `duckduckgo`, `serpapi`, or `google`
- `PAWGRAB_SERPAPI_KEY`
- `PAWGRAB_GOOGLE_SEARCH_API_KEY`
- `PAWGRAB_GOOGLE_SEARCH_CX`

## Crawl Limits

- `PAWGRAB_MAX_CRAWL_PAGES` - default `500`
- `PAWGRAB_MAX_CRAWL_DEPTH` - default `10`
- `PAWGRAB_MAX_TIMEOUT` - default `120000` ms

## SSE

- `PAWGRAB_SSE_MAX_DURATION` - default `3600` seconds, max SSE stream duration

## Concurrency

- `PAWGRAB_MIN_CONCURRENCY` - default `1`
- `PAWGRAB_MAX_CONCURRENCY` - default `10`
- `PAWGRAB_MEMORY_THRESHOLD_PERCENT` - default `85.0`, scales down concurrency above this

## Other

- `PAWGRAB_MONITOR_TTL` - default `86400` seconds, how long to keep previous content for diff
- `PAWGRAB_WORD_COUNT_THRESHOLD` - default `0` (off), min words per text block
- `PAWGRAB_REDIS_OPERATION_TIMEOUT` - default `5.0` seconds
- `PAWGRAB_WEBHOOK_TIMEOUT` - default `15` seconds
- `PAWGRAB_WEBHOOK_RETRIES` - default `3`
- `PAWGRAB_WORKER_MAX_JOBS` - default `5`
- `PAWGRAB_WORKER_JOB_TIMEOUT` - default `600` seconds
- `PAWGRAB_CHECKPOINT_INTERVAL` - default `10` pages
