"""FastAPI application entrypoint.

Run locally:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Or via Docker (see docker-compose.yml at the project root of ``/backend``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import api_router_v1
from app.core.config import settings
from app.core.database import dispose_engine
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis_client, get_redis_client
from app.middlewares import AccessLogMiddleware, RequestIDMiddleware
from app.utils.bootstrap import ensure_bootstrap_admin

# Configure logging before anything else so import-time messages are formatted.
configure_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Application start-up & shut-down hooks."""
    log.info(
        "app.starting",
        environment=settings.APP_ENV,
        version=settings.APP_VERSION,
    )

    # Touch Redis so we fail-fast on misconfiguration.
    try:
        await get_redis_client().ping()
        log.info("redis.connected")
    except Exception as exc:  # noqa: BLE001
        log.warning("redis.unavailable", error=str(exc))

    # Optional bootstrap admin.
    try:
        await ensure_bootstrap_admin(
            settings.BOOTSTRAP_ADMIN_EMAIL,
            settings.BOOTSTRAP_ADMIN_PASSWORD,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("bootstrap.admin_failed", error=str(exc))

    log.info("app.ready")
    try:
        yield
    finally:
        log.info("app.shutting_down")
        await close_redis_client()
        await dispose_engine()
        log.info("app.stopped")


def create_app() -> FastAPI:
    """Factory used by Uvicorn and tests."""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Backend API for the Digital Goods Arbitrage Platform. "
            "Milestone 1: foundation, authentication, and infrastructure."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
        debug=settings.DEBUG,
    )

    # --- Middlewares (order matters: outermost listed first) ----------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestIDMiddleware)

    # --- Routers ------------------------------------------------------------
    app.include_router(api_router_v1, prefix=settings.API_V1_PREFIX)

    # --- Exception handlers -------------------------------------------------
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        log.warning(
            "http.exception",
            status_code=exc.status_code,
            detail=exc.detail,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None) or {},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        log.info(
            "http.validation_error",
            path=request.url.path,
            errors=exc.errors(),
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        log.exception("http.unhandled_exception", path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    # --- Root ---------------------------------------------------------------
    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
            "api": settings.API_V1_PREFIX + "/v1",
        }

    return app


app = create_app()
