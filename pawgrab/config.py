"""Application configuration via environment variables."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "PAWGRAB_"}

    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "info"
    api_key: str = ""

    redis_url: str = "redis://localhost:6379/0"
    redis_operation_timeout: float = Field(default=5.0, ge=0.5, le=30.0)

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    llm_provider: str = "openai"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"

    browser_pool_size: int = Field(default=5, ge=1, le=20)
    browser_type: str = "chromium"
    browser_standby_recycle: bool = True
    browser_session_profiles: bool = True
    browser_trace_enabled: bool = False

    rate_limit_rpm: int = Field(default=60, ge=1)
    api_rate_limit_rpm: int = Field(default=600, ge=1)
    api_rate_limits: str = ""

    respect_robots: bool = True
    robots_cache_ttl: int = Field(default=3600, ge=0)
    robots_fetch_timeout: int = Field(default=10, ge=1, le=60)

    stealth_mode: bool = True
    max_challenge_retries: int = Field(default=2, ge=0, le=10)
    impersonate: str = ""
    solve_cloudflare: bool = True

    captcha_provider: str = ""
    captcha_api_key: str = ""

    proxy_url: str = ""
    proxy_urls: str = ""
    proxy_rotation_policy: Literal["round_robin", "random", "least_used"] = "round_robin"
    proxy_health_check: bool = True
    proxy_health_check_interval: int = Field(default=300, ge=10)
    proxy_offer_limit: int = Field(default=25, ge=1)
    proxy_evict_after_failures: int = Field(default=3, ge=1)
    proxy_backoff_seconds: int = Field(default=60, ge=1)

    search_provider: Literal["duckduckgo", "serpapi", "google"] = "duckduckgo"
    serpapi_key: str = ""
    google_search_api_key: str = ""
    google_search_cx: str = ""

    webhook_timeout: int = Field(default=15, ge=1, le=120)
    webhook_retries: int = Field(default=3, ge=0, le=10)

    sitemap_fetch_timeout: int = Field(default=15, ge=1, le=120)

    monitor_ttl: int = Field(default=86400, ge=0)

    http3: bool = False

    memory_threshold_percent: float = Field(default=85.0, ge=0, le=100)
    min_concurrency: int = Field(default=1, ge=1)
    max_concurrency: int = Field(default=10, ge=1)

    worker_max_jobs: int = Field(default=5, ge=1, le=50)
    worker_job_timeout: int = Field(default=600, ge=30, le=7200)
    checkpoint_interval: int = Field(default=10, ge=1, le=100)

    sse_max_duration: int = Field(default=3600, ge=60, le=86400)

    cache_ttl: int = Field(default=0, ge=0)

    max_timeout: int = Field(default=120000, ge=1000)

    plugins: str = ""
    trusted_proxy_ips: str = ""

    storage_backend: str = ""
    storage_path: str = "./pawgrab_data"
    s3_bucket: str = ""
    s3_prefix: str = "pawgrab"
    s3_region: str = "us-east-1"
    s3_endpoint_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""


settings = Settings()
