"""FastAPI application entrypoint.

Run locally:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Or via Docker (see docker-compose.yml at the project root of ``/backend``).
"""

from __future__ import annotations

import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import api_router_v1
from app.core.config import settings
from app.core.database import dispose_engine
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis_client, get_redis_client
from app.middlewares import AccessLogMiddleware, RequestIDMiddleware
from app.utils.bootstrap import ensure_bootstrap_admin
from app.workers import FulfillmentWorker, OrderPollWorker, PricingScanWorker

# Configure logging before anything else so import-time messages are formatted.
configure_logging()
log = get_logger(__name__)

# Ensure web fonts are served with the correct MIME type (Windows doesn't
# register these by default, which otherwise serves them as text/plain).
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")


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

    # Background workers. Skipped in tests; Redis locks/kill-switches still
    # govern them at runtime even when enabled here.
    workers: list[object] = []
    if settings.APP_ENV != "test":
        if settings.PRICING_ENGINE_ENABLED:
            try:
                pricing_worker = PricingScanWorker()
                pricing_worker.start()
                workers.append(pricing_worker)
            except Exception as exc:  # noqa: BLE001 — never block startup
                log.warning("pricing.worker_start_failed", error=str(exc))
        if settings.FULFILLMENT_ENABLED:
            try:
                fulfillment_worker = FulfillmentWorker()
                fulfillment_worker.start()
                workers.append(fulfillment_worker)
                poll_worker = OrderPollWorker()
                poll_worker.start()
                workers.append(poll_worker)
            except Exception as exc:  # noqa: BLE001 — never block startup
                log.warning("fulfillment.worker_start_failed", error=str(exc))

    log.info("app.ready")
    try:
        yield
    finally:
        log.info("app.shutting_down")
        for worker in workers:
            try:
                await worker.stop()  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                log.warning("worker.stop_failed", error=str(exc))
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
    @app.get("/api", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
            "api": settings.API_V1_PREFIX + "/v1",
        }

    # --- Static dashboard SPA (served by this same app) ---------------------
    # The dashboard SPA lives in the repo-root ``dashboard/`` folder (split out
    # of the backend package), but is still served by this same FastAPI app so
    # the product deploys as one application on one cloud.
    static_dir = Path(__file__).resolve().parents[2] / "dashboard"
    if static_dir.is_dir():
        # Real asset files (css/js/vendor/assets) are served directly.
        if (static_dir / "assets").is_dir():
            app.mount(
                "/assets",
                StaticFiles(directory=static_dir / "assets"),
                name="assets",
            )
        if (static_dir / "css").is_dir():
            app.mount("/css", StaticFiles(directory=static_dir / "css"), name="css")
        if (static_dir / "js").is_dir():
            app.mount("/js", StaticFiles(directory=static_dir / "js"), name="js")
        if (static_dir / "vendor").is_dir():
            app.mount(
                "/vendor",
                StaticFiles(directory=static_dir / "vendor"),
                name="vendor",
            )

        index_file = static_dir / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str) -> FileResponse:
            # API + docs are matched by their routers first; anything else
            # returns the SPA so client-side routing works on refresh. Guard
            # the API/docs prefixes so an unknown API path returns a real 404
            # rather than the SPA HTML.
            if full_path.startswith(("api/", "docs", "openapi.json", "redoc")):
                raise HTTPException(status_code=404, detail="Not found")
            return FileResponse(index_file)

    return app


app = create_app()
