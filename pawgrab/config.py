"""Application configuration via environment variables."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "PAWGRAB_"}

    # API
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "info"
    api_key: str = ""  # empty = no auth required

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Browser
    browser_pool_size: int = Field(default=3, ge=1, le=20)
    browser_type: str = "chromium"  # chromium, firefox, webkit

    # Rate limiting (requests per minute per domain)
    rate_limit_rpm: int = Field(default=60, ge=1)

    # Robots.txt
    respect_robots: bool = True
    robots_cache_ttl: int = Field(default=3600, ge=0)
    robots_fetch_timeout: int = Field(default=10, ge=1, le=60)

    # Anti-bot / stealth
    stealth_mode: bool = True
    max_challenge_retries: int = Field(default=2, ge=0, le=10)
    impersonate: str = ""  # curl_cffi target, e.g. "chrome124". Empty = random
    solve_cloudflare: bool = True

    # Proxy
    proxy_url: str = ""
    proxy_urls: str = ""  # comma-separated list for rotation
    proxy_rotation_policy: Literal["round_robin", "random", "least_used"] = "round_robin"
    proxy_health_check: bool = True
    proxy_health_check_interval: int = Field(default=300, ge=10)
    proxy_offer_limit: int = Field(default=25, ge=1)
    proxy_evict_after_failures: int = Field(default=3, ge=1)
    proxy_backoff_seconds: int = Field(default=60, ge=1)

    # Search
    search_provider: Literal["duckduckgo", "serpapi", "google"] = "duckduckgo"
    serpapi_key: str = ""
    google_search_api_key: str = ""
    google_search_cx: str = ""

    # Webhook
    webhook_timeout: int = Field(default=15, ge=1, le=120)
    webhook_retries: int = Field(default=3, ge=0, le=10)

    # Sitemap
    sitemap_fetch_timeout: int = Field(default=15, ge=1, le=120)

    # Change tracking / monitoring
    monitor_ttl: int = Field(default=86400, ge=0)

    # HTTP/3 (QUIC)
    http3: bool = False

    # Memory-adaptive dispatcher
    memory_threshold_percent: float = Field(default=85.0, ge=0, le=100)
    min_concurrency: int = Field(default=1, ge=1)
    max_concurrency: int = Field(default=10, ge=1)

    # Worker
    worker_max_jobs: int = Field(default=5, ge=1, le=50)
    worker_job_timeout: int = Field(default=600, ge=30, le=7200)
    checkpoint_interval: int = Field(default=10, ge=1, le=100)

    # Redis operations
    redis_operation_timeout: float = Field(default=5.0, ge=0.5, le=30.0)

    # API-level rate limiting (requests per minute per client)
    api_rate_limit_rpm: int = Field(default=600, ge=1)

    # SSE
    sse_max_duration: int = Field(default=3600, ge=60, le=86400)

    # Safety limits
    max_timeout: int = Field(default=120000, ge=1000)


settings = Settings()
