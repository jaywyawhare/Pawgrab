# Configuration

All settings are environment variables with `PAWGRAB_` prefix. Copy `.env.example` to `.env` to get started.

## Server

| Variable | Default | Description |
|----------|---------|-------------|
| `PAWGRAB_HOST` | `0.0.0.0` | Server bind address |
| `PAWGRAB_PORT` | `8000` | Server port |
| `PAWGRAB_LOG_LEVEL` | `info` | Log level (`debug`, `info`, `warning`, `error`) |
| `PAWGRAB_API_KEY` | *(empty)* | API key for Bearer auth. Empty = no auth |

## Redis

| Variable | Default | Description |
|----------|---------|-------------|
| `PAWGRAB_REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL. Required for crawl, batch, health, idempotency |
| `PAWGRAB_REDIS_OPERATION_TIMEOUT` | `5.0` | Redis operation timeout (seconds) |

## OpenAI

| Variable | Default | Description |
|----------|---------|-------------|
| `PAWGRAB_OPENAI_API_KEY` | *(empty)* | Required for `/v1/extract` with LLM strategy |
| `PAWGRAB_OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model for extraction |

## Browser

| Variable | Default | Description |
|----------|---------|-------------|
| `PAWGRAB_BROWSER_POOL_SIZE` | `3` | Number of Patchright browser instances |
| `PAWGRAB_BROWSER_TIMEOUT` | `30000` | Browser page timeout (ms) |
| `PAWGRAB_BROWSER_TYPE` | `chromium` | Browser engine: `chromium`, `firefox`, `webkit` |
| `PAWGRAB_STEALTH_MODE` | `true` | Enable fingerprint evasion |
| `PAWGRAB_MAX_CHALLENGE_RETRIES` | `2` | Max anti-bot challenge retries |
| `PAWGRAB_IMPERSONATE` | *(random)* | curl_cffi TLS target (e.g., `chrome124`) |

## Rate Limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `PAWGRAB_RATE_LIMIT_RPM` | `60` | Per-domain rate limit (requests/min) |
| `PAWGRAB_API_RATE_LIMIT_RPM` | `600` | API-level per-client rate limit |
| `PAWGRAB_RESPECT_ROBOTS` | `true` | Respect robots.txt rules |

## Proxy

| Variable | Default | Description |
|----------|---------|-------------|
| `PAWGRAB_PROXY_URL` | *(empty)* | Single proxy URL |
| `PAWGRAB_PROXY_URLS` | *(empty)* | Comma-separated proxy list for rotation |
| `PAWGRAB_PROXY_ROTATION_POLICY` | `round_robin` | `round_robin`, `random`, `least_used` |
| `PAWGRAB_PROXY_HEALTH_CHECK` | `true` | Enable proxy health checking |
| `PAWGRAB_PROXY_HEALTH_CHECK_INTERVAL` | `300` | Health check interval (seconds) |
| `PAWGRAB_PROXY_OFFER_LIMIT` | `25` | Skip proxy after N consecutive offers |
| `PAWGRAB_PROXY_EVICT_AFTER_FAILURES` | `3` | Soft-evict after N failures |
| `PAWGRAB_PROXY_BACKOFF_SECONDS` | `60` | Backoff cooldown (seconds) |

## Search

| Variable | Default | Description |
|----------|---------|-------------|
| `PAWGRAB_SEARCH_PROVIDER` | `duckduckgo` | `duckduckgo`, `serpapi`, `google` |
| `PAWGRAB_SERPAPI_KEY` | *(empty)* | SerpAPI key |
| `PAWGRAB_GOOGLE_SEARCH_API_KEY` | *(empty)* | Google Custom Search API key |
| `PAWGRAB_GOOGLE_SEARCH_CX` | *(empty)* | Google Custom Search engine ID |

## Crawl Limits

| Variable | Default | Description |
|----------|---------|-------------|
| `PAWGRAB_MAX_CRAWL_PAGES` | `500` | Max pages per crawl job |
| `PAWGRAB_MAX_CRAWL_DEPTH` | `10` | Max crawl depth |
| `PAWGRAB_MAX_TIMEOUT` | `120000` | Maximum timeout (ms) |

## SSE

| Variable | Default | Description |
|----------|---------|-------------|
| `PAWGRAB_SSE_MAX_DURATION` | `3600` | Max SSE stream duration (seconds) |

## Concurrency

| Variable | Default | Description |
|----------|---------|-------------|
| `PAWGRAB_MIN_CONCURRENCY` | `1` | Minimum concurrent requests |
| `PAWGRAB_MAX_CONCURRENCY` | `10` | Maximum concurrent requests |
| `PAWGRAB_MEMORY_THRESHOLD_PERCENT` | `85.0` | Scale down concurrency above this |

## Worker

| Variable | Default | Description |
|----------|---------|-------------|
| `PAWGRAB_WORKER_MAX_JOBS` | `5` | Max concurrent worker jobs |
| `PAWGRAB_WORKER_JOB_TIMEOUT` | `600` | Job timeout (seconds) |
| `PAWGRAB_CHECKPOINT_INTERVAL` | `10` | Pages between Redis checkpoints |

## Other

| Variable | Default | Description |
|----------|---------|-------------|
| `PAWGRAB_MONITOR_TTL` | `86400` | Content diff TTL (seconds) |
| `PAWGRAB_WORD_COUNT_THRESHOLD` | `0` | Min words per text block (0 = off) |
| `PAWGRAB_WEBHOOK_TIMEOUT` | `15` | Webhook timeout (seconds) |
| `PAWGRAB_WEBHOOK_RETRIES` | `3` | Webhook retry attempts |
