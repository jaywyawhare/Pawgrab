"""Capability self-diagnosis — report which features are usable with the current config.

Unlike the infra ``/health`` check (redis/browser/memory liveness), this reports,
per capability, whether it will actually *work* given the configured keys, proxies,
and backends. The guiding rule is conservative: a capability is only ``ok`` when it
is provably usable without side effects; something configured but unverifiable (a
local Ollama endpoint, proxies not yet health-checked) is ``warn``, not ``ok``, so
the report never over-promises. Optional features that are simply absent are ``off``.
"""

from __future__ import annotations

from pawgrab.config import settings

_LLM_KEY_FIELDS = {
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
    "gemini": "gemini_api_key",
}


def _cap(status: str, message: str, **detail) -> dict:
    out = {"status": status, "message": message}
    if detail:
        out["detail"] = detail
    return out


def _llm_capability(provider: str) -> dict:
    """Readiness of one LLM provider: ollama is local (warn, unverifiable), others need a key."""
    if provider == "ollama":
        return _cap("warn", f"local Ollama at {settings.ollama_base_url} (not verified)", provider=provider)
    key = getattr(settings, _LLM_KEY_FIELDS.get(provider, ""), "")
    if key:
        return _cap("ok", f"{provider} key configured", provider=provider)
    return _cap("off", f"no {provider} API key set", provider=provider)


def _llm() -> dict:
    cap = _llm_capability(settings.llm_provider)
    fb = settings.llm_fallback_provider
    if fb and fb != settings.llm_provider:
        cap.setdefault("detail", {})["fallback"] = _llm_capability(fb)["status"]
    return cap


def _captcha() -> dict:
    provider, key = settings.captcha_provider, settings.captcha_api_key
    if provider and key:
        return _cap("ok", f"{provider} solver configured", provider=provider)
    if provider or key:
        return _cap("warn", "captcha solver partially configured (need both provider and key)")
    return _cap("off", "no captcha solver configured (optional)")


def _proxies() -> dict:
    configured = bool(settings.proxy_url or settings.proxy_urls or settings.proxy_urls_premium)
    if not configured:
        return _cap("off", "no proxies configured (optional)")
    from pawgrab import dependencies

    pool = dependencies._proxy_pool
    if pool is None:
        return _cap("warn", "proxies configured, pool not started (health-checks on startup)")
    stats = pool.pool_stats()
    if stats["active"] > 0:
        return _cap("ok", f"{stats['active']}/{stats['total']} proxies healthy", **stats)
    return _cap("warn", "proxies configured but none currently healthy", **stats)


def _search() -> dict:
    provider = settings.search_provider
    if provider == "google":
        if settings.google_search_api_key and settings.google_search_cx:
            return _cap("ok", "Google Custom Search configured", provider=provider)
        return _cap("warn", "google provider selected but missing API key or CX", provider=provider)
    return _cap("ok", f"keyless meta-search ({provider})", provider=provider)


def _storage() -> dict:
    backend = settings.storage_backend
    if backend == "s3":
        if settings.s3_bucket and settings.s3_access_key and settings.s3_secret_key:
            return _cap("ok", f"S3 bucket '{settings.s3_bucket}'", backend="s3")
        return _cap("warn", "S3 backend selected but missing bucket or credentials", backend="s3")
    return _cap("ok", f"local filesystem ({settings.storage_path})", backend=backend or "local")


def _browser() -> dict:
    from pawgrab import dependencies

    if settings.browser_cdp_url:
        return _cap("ok", "external Chromium over CDP")
    pool = dependencies._browser_pool
    if pool is not None and getattr(pool, "_started", False):
        return _cap("ok", "browser pool running", pool=pool.stats())
    return _cap("warn", "browser pool not started (launches on first request)")


def run_diagnostics() -> dict:
    """Collect per-capability readiness. ``ok`` only when provably usable; see module docstring.

    Overall status is ``degraded`` when a capability the operator explicitly
    selected is misconfigured (``warn`` on llm/search/storage), else ``ok``.
    """
    caps: dict[str, dict] = {
        "fetch": _cap("ok", "HTTP fetch via curl_cffi TLS impersonation"),
        "browser": _browser(),
        "llm": _llm(),
        "captcha": _captcha(),
        "proxies": _proxies(),
        "search": _search(),
        "storage": _storage(),
    }
    summary = {s: sum(1 for c in caps.values() if c["status"] == s) for s in ("ok", "warn", "off")}
    degraded = any(caps[k]["status"] == "warn" for k in ("llm", "search", "storage"))
    return {"status": "degraded" if degraded else "ok", "summary": summary, "capabilities": caps}
