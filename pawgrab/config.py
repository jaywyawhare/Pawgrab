"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "PAWGRAB_"}

    # API
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"
    api_key: str = ""  # empty = no auth required

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Browser
    browser_pool_size: int = 3
    browser_timeout: int = 30000

    # Rate limiting (requests per minute per domain)
    rate_limit_rpm: int = 60

    # Robots.txt
    respect_robots: bool = True

    # Anti-bot / stealth
    stealth_mode: bool = True
    max_challenge_retries: int = 2
    impersonate: str = ""  # curl_cffi target, e.g. "chrome124". Empty = random

    # Proxy (single URL or comma-separated list for rotation)
    proxy_url: str = ""  # e.g. http://user:pass@host:port or socks5://host:port
    proxy_urls: str = ""  # comma-separated list for rotation on retries
    proxy_rotation_policy: str = "round_robin"  # round_robin, random, least_used
    proxy_health_check: bool = True
    proxy_health_check_interval: int = 300  # seconds between health checks
    proxy_offer_limit: int = 25  # max consecutive offers before skip
    proxy_evict_after_failures: int = 3  # recent failures before soft-eviction
    proxy_backoff_seconds: int = 60  # backoff duration after failure

    # Search
    search_provider: str = "duckduckgo"  # duckduckgo, serpapi, google
    serpapi_key: str = ""
    google_search_api_key: str = ""
    google_search_cx: str = ""

    # Change tracking / monitoring
    monitor_ttl: int = 86400  # seconds to keep previous content for diff

    # Content processing defaults
    word_count_threshold: int = 0  # 0 = disabled; min words per text block

    # Browser
    browser_type: str = "chromium"  # chromium, firefox, webkit

    # Memory-adaptive dispatcher
    memory_threshold_percent: float = 85.0  # scale down when memory usage exceeds this
    min_concurrency: int = 1
    max_concurrency: int = 10

    # Safety limits
    max_timeout: int = 120000
    max_crawl_pages: int = 500
    max_crawl_depth: int = 10


settings = Settings()
