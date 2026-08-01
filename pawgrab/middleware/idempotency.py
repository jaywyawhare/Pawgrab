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
_INFLIGHT_TTL = 300  # sentinel lifetime while the first request is still running


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

        # Bind the request body to the key: reusing a key with a different payload
        # must not silently return the first payload's response.
        body_bytes = await request.body()
        body_hash = hashlib.sha256(body_bytes).hexdigest()[:16]

        try:
            from pawgrab.queue.manager import get_redis

            redis = await get_redis()
        except Exception:
            return await call_next(request)

        # Atomically claim the key. If another request already claimed it, decide
        # between replay (done), conflict (in-flight), or payload mismatch.
        claimed = await redis.set(
            cache_key,
            orjson.dumps({"state": "in_progress", "body_hash": body_hash}).decode(),
            nx=True,
            ex=_INFLIGHT_TTL,
        )
        if not claimed:
            cached = await redis.get(cache_key)
            data = {}
            if cached is not None:
                try:
                    data = orjson.loads(cached)
                except Exception:
                    data = {}
            if data.get("body_hash") and data["body_hash"] != body_hash:
                return JSONResponse(
                    status_code=422,
                    content={"error": "Idempotency-Key reused with a different request body"},
                    headers={"X-Idempotency-Replay": "false"},
                )
            if data.get("state") == "in_progress":
                return JSONResponse(
                    status_code=409,
                    content={"error": "A request with this Idempotency-Key is still in progress"},
                    headers={"X-Idempotency-Replay": "false"},
                )
            return JSONResponse(
                status_code=data.get("status_code", 202),
                content=data.get("body"),
                headers={"X-Idempotency-Replay": "true"},
            )

        response: Response = await call_next(request)

        if 200 <= response.status_code < 300:
            body = b""
            try:
                async for chunk in response.body_iterator:
                    body += chunk.encode() if isinstance(chunk, str) else chunk

                cache_data = orjson.dumps(
                    {
                        "state": "done",
                        "body_hash": body_hash,
                        "status_code": response.status_code,
                        "body": orjson.loads(body),
                    }
                ).decode()
                await redis.set(cache_key, cache_data, ex=_CACHE_TTL)
            except Exception:
                logger.warning("idempotency_cache_failed", key=idem_key)

            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        # Non-2xx: release the in-flight claim so the client can retry.
        try:
            await redis.delete(cache_key)
        except Exception:
            pass
        return response
