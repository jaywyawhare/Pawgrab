# Deployment

## Docker Compose (Recommended)

The easiest way to deploy Pawgrab in production:

```bash
git clone https://github.com/jaywyawhare/Pawgrab.git
cd Pawgrab
cp .env.example .env
# Edit .env with your settings
docker compose up -d
```

This starts three services:

### API Server
- **Port:** 8000
- **Memory limit:** 2GB
- **Health check:** Built-in
- **Auto-restart:** `unless-stopped`

### ARQ Worker
- **Purpose:** Processes async crawl and batch jobs
- **Memory limit:** 2GB
- **Max concurrent jobs:** 5 (configurable)
- **Job timeout:** 600s (configurable)

### Redis
- **Purpose:** Job queue, idempotency cache, crawl checkpoints
- **Memory limit:** 256MB
- **Eviction policy:** LRU (allkeys-lru)
- **Health check:** Built-in

## Docker Compose File

```yaml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      redis:
        condition: service_healthy
    deploy:
      resources:
        limits:
          memory: 2G
    restart: unless-stopped

  worker:
    build: .
    command: python -m pawgrab.queue.worker
    env_file: .env
    depends_on:
      redis:
        condition: service_healthy
    deploy:
      resources:
        limits:
          memory: 2G
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3
    restart: unless-stopped
```

## Manual Deployment

### Requirements
- Python 3.11+
- Redis (for crawl/batch/idempotency)
- Chromium browser (for JS rendering)

### Setup

```bash
# Install
pip install pawgrab
patchright install chromium

# Start Redis
docker run -d -p 6379:6379 redis:7-alpine

# Configure
cp .env.example .env

# Start API server
pawgrab serve --host 0.0.0.0 --port 8000

# Start worker (in another terminal)
python -m pawgrab.queue.worker
```

## Reverse Proxy (nginx)

Example nginx configuration:

```nginx
upstream pawgrab {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name scraper.example.com;

    location / {
        proxy_pass http://pawgrab;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # SSE streaming support
    location ~ ^/v1/crawl/.*/stream$ {
        proxy_pass http://pawgrab;
        proxy_set_header Host $host;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
    }
}
```

## Environment Variables

Key production settings:

```bash
# Security
PAWGRAB_API_KEY=your-secret-api-key

# Redis
PAWGRAB_REDIS_URL=redis://redis:6379/0

# Browser pool
PAWGRAB_BROWSER_POOL_SIZE=5
PAWGRAB_STEALTH_MODE=true

# Rate limits
PAWGRAB_RATE_LIMIT_RPM=60
PAWGRAB_API_RATE_LIMIT_RPM=600

# Crawl limits
PAWGRAB_MAX_CRAWL_PAGES=500
PAWGRAB_WORKER_MAX_JOBS=5

# Concurrency
PAWGRAB_MAX_CONCURRENCY=10
PAWGRAB_MEMORY_THRESHOLD_PERCENT=85.0
```

See the full [Configuration](configuration.md) reference for all 80+ options.

## Health Monitoring

The `/health` endpoint returns component status:

```bash
curl http://localhost:8000/health
```

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
- **ok** — All checks pass
- **degraded** — Non-critical failure (e.g., browser pool down)
- **unhealthy** — Critical failure (e.g., Redis down)

## Scaling

### Horizontal Scaling
- Run multiple API instances behind a load balancer
- Run multiple workers for higher crawl throughput
- All instances share the same Redis for job coordination

### Vertical Scaling
- Increase `PAWGRAB_BROWSER_POOL_SIZE` for more concurrent browser sessions
- Increase `PAWGRAB_MAX_CONCURRENCY` for more parallel requests
- Adjust `PAWGRAB_MEMORY_THRESHOLD_PERCENT` to control memory-adaptive scaling
