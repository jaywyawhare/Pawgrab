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
    # Hard cap on chunks sent to the LLM per extraction — bounds cost/latency on
    # huge pages (a chunked extract would otherwise fan out unboundedly).
    llm_max_chunks: int = Field(default=20, ge=1, le=200)
    llm_max_output_tokens: int = Field(default=4096, ge=256, le=32768)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"

    browser_pool_size: int = Field(default=5, ge=1, le=20)
    # Max concurrent per-session browser contexts before LRU eviction (bounds
    # context + temp-dir growth when sessions are never explicitly closed).
    browser_max_sessions: int = Field(default=50, ge=1, le=500)
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
    # On a transient robots.txt fetch error: fail open (allow, default) or closed
    # (deny). A clean 404 always means "no robots.txt" => allowed, regardless.
    robots_fail_closed: bool = False

    # SSRF protection: block fetch/webhook targets that resolve to private,
    # loopback, link-local (cloud-metadata), or reserved addresses. Disable only
    # for trusted local development. allow_private_urls fully bypasses the check.
    ssrf_protection: bool = True
    allow_private_urls: bool = False
    # Max redirect hops to follow on the curl path (each hop is SSRF-revalidated).
    max_redirects: int = Field(default=10, ge=0, le=30)
    # Retry a failed TLS handshake with verification disabled. Off by default —
    # enabling it silently downgrades security for self-signed/expired-cert sites.
    allow_insecure_ssl: bool = False

    stealth_mode: bool = True
    max_challenge_retries: int = Field(default=3, ge=0, le=10)
    impersonate: str = ""
    solve_cloudflare: bool = True

    # Auth / CORS. With no api_key the API is unauthenticated; that is only
    # allowed when allow_unauthenticated is explicitly set (else `serve` refuses
    # to start). CORS origins are configured independently of the api_key —
    # wildcard is never paired with open auth automatically.
    allow_unauthenticated: bool = False
    cors_allow_origins: str = ""  # comma-separated; empty = no cross-origin

    # Human-like input on the browser path (Bezier mouse, per-char typing, wheel
    # scroll). Scores higher against behavioural anti-bot layers than instant clicks.
    humanize_interactions: bool = True
    # Resolve a proxy's exit-IP geolocation and align the browser timezone/locale/
    # geolocation to it, so the fingerprint agrees with the IP the site sees.
    geoip_coherence: bool = True
    geoip_timeout_seconds: float = Field(default=5.0, ge=0.5, le=30.0)
    # Deterministic fingerprint seed. 0 = fresh random identity per context; any
    # non-zero value pins one coherent identity (GPU/screen/UA/timezone) across runs.
    fingerprint_seed: int = 0

    captcha_provider: str = ""
    captcha_api_key: str = ""

    proxy_url: str = ""
    proxy_urls: str = ""
    # Premium tier (residential/mobile). Escalated to on anti-bot blocks (403/429/
    # challenge) — the datacenter->residential "auto" pattern. Empty = no escalation.
    proxy_urls_premium: str = ""
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
    # HMAC-SHA256 signing secret for webhook payloads. When set, deliveries carry
    # an X-Pawgrab-Signature header so receivers can verify authenticity.
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
    # Lifetime of a job's Redis status hash. Refreshed on every update so a long
    # crawl's status never expires mid-run; must exceed worker_job_timeout.
    job_ttl_seconds: int = Field(default=14400, ge=3600)

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
