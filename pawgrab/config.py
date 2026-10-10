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
    llm_provider: Literal["openai", "anthropic", "gemini", "ollama"] = "openai"

    llm_max_chunks: int = Field(default=20, ge=1, le=200)
    llm_max_output_tokens: int = Field(default=4096, ge=256, le=32768)

    llm_max_retries: int = Field(default=2, ge=0, le=5)
    llm_fallback_provider: Literal["", "openai", "anthropic", "gemini", "ollama"] = ""
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"
    browser_pool_size: int = Field(default=5, ge=1, le=20)

    browser_max_sessions: int = Field(default=50, ge=1, le=500)
    browser_type: str = "chromium"
    browser_cdp_url: str = Field(
        default="",
        description="CDP endpoint of an externally-run patched Chromium (e.g. CloakBrowser) to connect to instead of launching locally; empty = launch locally",
    )
    browser_cdp_timeout_ms: int = Field(default=30000, ge=1000, le=120000)
    browser_standby_recycle: bool = True
    browser_session_profiles: bool = True
    browser_trace_enabled: bool = False
    rate_limit_rpm: int = Field(default=60, ge=1)
    api_rate_limit_rpm: int = Field(default=600, ge=1)
    api_rate_limits: str = ""
    respect_robots: bool = True
    robots_cache_ttl: int = Field(default=3600, ge=0)
    robots_fetch_timeout: int = Field(default=10, ge=1, le=60)

    robots_fail_closed: bool = False

    ssrf_protection: bool = True
    allow_private_urls: bool = False

    max_redirects: int = Field(default=10, ge=0, le=30)

    allow_insecure_ssl: bool = False
    stealth_mode: bool = True
    max_challenge_retries: int = Field(default=3, ge=0, le=10)
    impersonate: str = ""
    solve_cloudflare: bool = True
    # When a fetch ends blocked (403/406/429/challenge), retry once with a fresh
    # TLS identity, the premium proxy tier, and forced JS rendering.
    fetch_escalation_retry: bool = True

    allow_unauthenticated: bool = False
    cors_allow_origins: str = ""

    humanize_interactions: bool = True

    geoip_coherence: bool = True
    geoip_timeout_seconds: float = Field(default=5.0, ge=0.5, le=30.0)

    fingerprint_seed: int = 0

    fingerprint_platform: Literal["macos", "windows"] = "macos"

    session_warming: bool = True
    captcha_provider: str = ""
    captcha_api_key: str = ""
    proxy_url: str = ""
    proxy_urls: str = ""

    proxy_urls_premium: str = ""
    proxy_rotation_policy: Literal["round_robin", "random", "least_used"] = "round_robin"
    proxy_health_check: bool = True
    proxy_health_check_interval: int = Field(default=300, ge=10)
    proxy_offer_limit: int = Field(default=25, ge=1)
    proxy_evict_after_failures: int = Field(default=3, ge=1)
    proxy_backoff_seconds: int = Field(default=60, ge=1)

    search_provider: Literal["duckduckgo", "bing", "brave", "mojeek", "yahoo", "startpage", "auto", "google"] = "duckduckgo"
    google_search_api_key: str = ""
    google_search_cx: str = ""

    search_engine_timeout: float = Field(default=12.0, ge=1.0, le=60.0)

    search_instant_answers: bool = True
    webhook_timeout: int = Field(default=15, ge=1, le=120)
    webhook_retries: int = Field(default=3, ge=0, le=10)

    webhook_secret: str = ""
    sitemap_fetch_timeout: int = Field(default=15, ge=1, le=120)
    monitor_ttl: int = Field(default=86400, ge=0)
    http3: bool = False
    memory_threshold_percent: float = Field(default=85.0, ge=0, le=100)
    min_concurrency: int = Field(default=1, ge=1)
    max_concurrency: int = Field(default=10, ge=1)
    worker_max_jobs: int = Field(default=5, ge=1, le=50)
    worker_job_timeout: int = Field(default=600, ge=30, le=7200)
    checkpoint_interval: int = Field(default=10, ge=1, le=100)

    job_ttl_seconds: int = Field(default=14400, ge=3600)
    sse_max_duration: int = Field(default=3600, ge=60, le=86400)
    cache_ttl: int = Field(default=0, ge=0)
    max_timeout: int = Field(default=120000, ge=1000)
    mcp_api_url: str = "http://localhost:8000"
    plugins: str = ""
    trusted_proxy_ips: str = ""
    adaptive_store_backend: Literal["auto", "redis", "disk"] = "auto"
    adaptive_min_score: float = Field(default=0.6, ge=0.0, le=1.0)
    adaptive_ttl: int = Field(default=2592000, ge=0)
    storage_backend: str = ""
    storage_path: str = "./pawgrab_data"
    s3_bucket: str = ""
    s3_prefix: str = "pawgrab"
    s3_region: str = "us-east-1"
    s3_endpoint_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""


settings = Settings()
