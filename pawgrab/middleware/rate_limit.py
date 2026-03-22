"""API-level rate limiting middleware."""

from __future__ import annotations

import asyncio
import time

from aiolimiter import AsyncLimiter
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from pawgrab.exceptions import ErrorCode
from pawgrab.models.common import ErrorResponse

_SKIP_PATHS = {"/health", "/status", "/docs", "/openapi.json", "/redoc", "/metrics"}
_CLEANUP_INTERVAL = 600
_LIMITER_IDLE_TTL = 600


class APIRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, rpm: int = 600) -> None:
        super().__init__(app)
        self._rpm = rpm
        self._limiters: dict[str, tuple[AsyncLimiter, float]] = {}
        self._lock = asyncio.Lock()
        self._last_cleanup = time.monotonic()
        self._key_limits: dict[str, int] = {}
        self._load_key_limits()

    def _load_key_limits(self):
        """Load per-key rate limits from config."""
        from pawgrab.config import settings
        if settings.api_rate_limits:
            try:
                import orjson
                self._key_limits = orjson.loads(settings.api_rate_limits)
            except Exception:
                pass

    def _get_client_key(self, request: Request) -> str:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and len(auth) > 7:
            return f"key:{auth[7:].strip()}"
        # Only trust X-Forwarded-For when the connecting IP is a configured trusted proxy.
        # Without this check, any client can spoof their IP to bypass rate limiting.
        from pawgrab.config import settings
        trusted = {ip.strip() for ip in settings.trusted_proxy_ips.split(",") if ip.strip()}
        client = request.client
        connecting_ip = client.host if client else None
        if trusted and connecting_ip in trusted:
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                return f"ip:{forwarded.split(',')[0].strip()}"
        return f"ip:{connecting_ip}" if connecting_ip else "ip:unknown"

    async def _get_limiter(self, key: str) -> AsyncLimiter:
        now = time.monotonic()
        entry = self._limiters.get(key)
        if entry is not None:
            limiter, _ = entry
            self._limiters[key] = (limiter, now)
            return limiter

        async with self._lock:
            entry = self._limiters.get(key)
            if entry is not None:
                limiter, _ = entry
                self._limiters[key] = (limiter, now)
                return limiter

            rpm = self._rpm
            if key.startswith("key:"):
                actual_key = key[4:]
                rpm = self._key_limits.get(actual_key, self._rpm)
            limiter = AsyncLimiter(rpm, 60)
            self._limiters[key] = (limiter, now)

            if now - self._last_cleanup > _CLEANUP_INTERVAL:
                self._last_cleanup = now
                stale = [
                    k
                    for k, (_, last_used) in self._limiters.items()
                    if now - last_used > _LIMITER_IDLE_TTL
                ]
                for k in stale:
                    del self._limiters[k]

            return limiter

    async def dispatch(self, request: Request, call_next):
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        key = self._get_client_key(request)
        limiter = await self._get_limiter(key)

        if not limiter.has_capacity():
            return JSONResponse(
                status_code=429,
                content=ErrorResponse(
                    error="Rate limit exceeded",
                    code=ErrorCode.RATE_LIMITED.value,
                    details=f"Limit: {self._rpm} requests per minute",
                    request_id=getattr(request.state, "request_id", None),
                ).model_dump(),
                headers={
                    "Retry-After": "60",
                    "X-RateLimit-Limit": str(self._rpm),
                    "X-RateLimit-Remaining": "0",
                },
            )

        await limiter.acquire()
        remaining = max(0, int(limiter.max_rate - getattr(limiter, "_level", 0)))

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self._rpm)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
