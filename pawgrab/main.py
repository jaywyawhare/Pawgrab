"""FastAPI application factory and lifespan."""

from __future__ import annotations

import hmac
import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from pawgrab.api import batch, crawl, extract, health, map, proxy, scrape, search
from pawgrab.config import settings
from pawgrab.dependencies import shutdown_browser_pool, shutdown_proxy_pool
from pawgrab.engine.fetcher import close_sessions
from pawgrab.exceptions import ErrorCode, PawgrabError
from pawgrab.models.common import ErrorResponse
from pawgrab.queue.manager import close_redis

from pawgrab import __version__

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
    logger.info("pawgrab_starting", version=__version__)
    yield
    logger.info("pawgrab_shutting_down")
    await shutdown_proxy_pool()
    await shutdown_browser_pool()
    await close_sessions()
    await close_redis()
    logger.info("pawgrab_stopped")


_STATUS_TO_CODE = {
    400: ErrorCode.VALIDATION_ERROR,
    401: ErrorCode.INVALID_API_KEY,
    403: ErrorCode.ROBOTS_BLOCKED,
    404: ErrorCode.RESOURCE_NOT_FOUND,
    429: ErrorCode.RATE_LIMITED,
    502: ErrorCode.FETCH_FAILED,
    503: ErrorCode.QUEUE_UNAVAILABLE,
    504: ErrorCode.TIMEOUT,
}


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
        request.state.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 1)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-API-Version"] = __version__
        response.headers["X-Response-Time"] = f"{duration_ms}ms"

        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response


class APIKeyMiddleware(BaseHTTPMiddleware):
    SKIP_PATHS = {"/health", "/status", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(self, request: Request, call_next):
        if not settings.api_key:
            return await call_next(request)

        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        key = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(key, settings.api_key):
            return JSONResponse(
                status_code=401,
                content=ErrorResponse(
                    error="Invalid or missing API key",
                    code=ErrorCode.INVALID_API_KEY.value,
                    request_id=getattr(request.state, "request_id", None),
                ).model_dump(),
            )
        return await call_next(request)


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Pawgrab",
        description=(
            "Fast, stealth web scraping API with content extraction, "
            "crawling, structured data extraction, and search capabilities."
        ),
        version=__version__,
        lifespan=lifespan,
    )

    @app.exception_handler(PawgrabError)
    async def pawgrab_error_handler(request: Request, exc: PawgrabError):
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error=exc.message,
                code=exc.code.value,
                details=exc.details,
                request_id=_request_id(request),
            ).model_dump(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        code = _STATUS_TO_CODE.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error=str(exc.detail),
                code=code.value,
                request_id=_request_id(request),
            ).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        fields = [
            f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}"
            for e in errors
            if len(e["loc"]) > 1
        ]
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                error="Validation error",
                code=ErrorCode.VALIDATION_ERROR.value,
                details="; ".join(fields) if fields else str(errors),
                request_id=_request_id(request),
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.error("unhandled_error", path=request.url.path, error=str(exc))
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error="Internal server error",
                code=ErrorCode.INTERNAL_ERROR.value,
                request_id=_request_id(request),
            ).model_dump(),
        )

    from pawgrab.middleware.idempotency import IdempotencyMiddleware
    from pawgrab.middleware.rate_limit import APIRateLimitMiddleware

    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(APIRateLimitMiddleware, rpm=settings.api_rate_limit_rpm)
    if settings.api_key:
        app.add_middleware(APIKeyMiddleware)
    app.add_middleware(RequestIDMiddleware)

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
