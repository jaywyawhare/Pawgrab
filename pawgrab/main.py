"""FastAPI application factory and lifespan."""

from __future__ import annotations

import hmac
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from pawgrab.api import batch, crawl, extract, health, map, proxy, scrape, search
from pawgrab.config import settings
from pawgrab.dependencies import shutdown_browser_pool, shutdown_proxy_pool
from pawgrab.engine.fetcher import close_sessions
from pawgrab.models.common import ErrorResponse
from pawgrab.queue.manager import close_redis

_VERSION = "0.0.1"

_is_production = settings.log_level.lower() not in ("debug",)

if _is_production:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
    )
else:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
    )

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("pawgrab_starting", version=_VERSION)
    yield
    logger.info("pawgrab_shutting_down")
    await shutdown_proxy_pool()
    await shutdown_browser_pool()
    await close_sessions()
    await close_redis()
    logger.info("pawgrab_stopped")


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
        request.state.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-API-Version"] = _VERSION
        return response


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Reject requests without a valid API key (when configured)."""

    SKIP_PATHS = {"/health", "/status", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(self, request: Request, call_next):
        if not settings.api_key:
            return await call_next(request)

        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        key = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(key, settings.api_key):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content=ErrorResponse(
                    success=False, error="Invalid or missing API key"
                ).model_dump(),
            )
        return await call_next(request)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Pawgrab",
        description="Web scraping API — clean output from any URL",
        version=_VERSION,
        lifespan=lifespan,
    )

    app.add_middleware(RequestIDMiddleware)
    if settings.api_key:
        app.add_middleware(APIKeyMiddleware)

    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not settings.api_key else [],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(scrape.router, prefix="/v1")
    app.include_router(crawl.router, prefix="/v1")
    app.include_router(extract.router, prefix="/v1")
    app.include_router(batch.router, prefix="/v1")
    app.include_router(map.router, prefix="/v1")
    app.include_router(search.router, prefix="/v1")
    app.include_router(proxy.router, prefix="/v1")

    return app


app = create_app()
