"""Idempotency key middleware for crawl and batch endpoints."""

from __future__ import annotations

import hashlib

import orjson
import structlog
from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger()

_IDEMPOTENT_PATHS = {"/v1/crawl", "/v1/batch/scrape"}
_CACHE_TTL = 86400


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method != "POST" or request.url.path not in _IDEMPOTENT_PATHS:
            return await call_next(request)

        idem_key = request.headers.get("Idempotency-Key")
        if not idem_key:
            return await call_next(request)

        # Scope the key to the client so one client can't replay another's response
        auth = request.headers.get("Authorization", "")
        if auth:
            client_id = hashlib.sha256(auth.encode()).hexdigest()[:16]
        else:
            client_id = request.client.host if request.client else "anon"
        cache_key = f"pawgrab:idempotency:{request.url.path}:{client_id}:{idem_key}"

        try:
            from pawgrab.queue.manager import get_redis
            redis = await get_redis()
        except Exception:
            return await call_next(request)

        cached = await redis.get(cache_key)
        if cached is not None:
            try:
                data = orjson.loads(cached)
                return JSONResponse(
                    status_code=data.get("status_code", 202),
                    content=data.get("body"),
                    headers={"X-Idempotency-Replay": "true"},
                )
            except Exception:
                await redis.delete(cache_key)

        response: Response = await call_next(request)

        if 200 <= response.status_code < 300:
            body = b""
            try:
                async for chunk in response.body_iterator:
                    body += chunk.encode() if isinstance(chunk, str) else chunk

                cache_data = orjson.dumps({
                    "status_code": response.status_code,
                    "body": orjson.loads(body),
                }).decode()
                await redis.set(cache_key, cache_data, ex=_CACHE_TTL)
            except Exception:
                logger.warning("idempotency_cache_failed", key=idem_key)

            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        return response
