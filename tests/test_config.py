import os
from unittest.mock import patch

import pytest

from pawgrab.config import Settings


@pytest.mark.parametrize(
    "attr,expected",
    [
        ("host", "0.0.0.0"),
        ("port", 8000),
        ("log_level", "info"),
        ("redis_url", "redis://localhost:6379/0"),
        ("rate_limit_rpm", 60),
        ("browser_pool_size", 5),
        ("proxy_rotation_policy", "round_robin"),
        ("search_provider", "duckduckgo"),
        ("respect_robots", True),
        ("stealth_mode", True),
        ("llm_provider", "openai"),
        ("storage_backend", ""),
        ("cache_ttl", 0),
    ],
)
def test_defaults(attr, expected):
    assert getattr(Settings(), attr) == expected


@pytest.mark.parametrize(
    "env_var,attr,value,expected",
    [
        ("PAWGRAB_PORT", "port", "9000", 9000),
        ("PAWGRAB_API_KEY", "api_key", "secret123", "secret123"),
        ("PAWGRAB_REDIS_URL", "redis_url", "redis://myhost:6379/1", "redis://myhost:6379/1"),
        ("PAWGRAB_OPENAI_API_KEY", "openai_api_key", "sk-test123", "sk-test123"),
        ("PAWGRAB_RATE_LIMIT_RPM", "rate_limit_rpm", "120", 120),
        ("PAWGRAB_BROWSER_POOL_SIZE", "browser_pool_size", "10", 10),
        ("PAWGRAB_PROXY_ROTATION_POLICY", "proxy_rotation_policy", "random", "random"),
        ("PAWGRAB_SEARCH_PROVIDER", "search_provider", "serpapi", "serpapi"),
        ("PAWGRAB_STORAGE_BACKEND", "storage_backend", "filesystem", "filesystem"),
    ],
)
def test_env_overrides(env_var, attr, value, expected):
    with patch.dict(os.environ, {env_var: value}):
        assert getattr(Settings(), attr) == expected


@pytest.mark.parametrize(
    "env_var,value",
    [
        ("PAWGRAB_PORT", "0"),
        ("PAWGRAB_PORT", "70000"),
        ("PAWGRAB_BROWSER_POOL_SIZE", "0"),
        ("PAWGRAB_BROWSER_POOL_SIZE", "21"),
        ("PAWGRAB_RATE_LIMIT_RPM", "0"),
        ("PAWGRAB_MEMORY_THRESHOLD_PERCENT", "101"),
    ],
)
def test_invalid_values_raise(env_var, value):
    from pydantic import ValidationError

    with patch.dict(os.environ, {env_var: value}):
        with pytest.raises(ValidationError):
            Settings()
