"""FastAPI application entrypoint.

Run locally:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Or via Docker (see docker-compose.yml at the project root of ``/backend``).
"""

from __future__ import annotations

import mimetypes
import os
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


def _find_dashboard_dir() -> Path | None:
    """Locate the dashboard SPA folder across local and container layouts.

    The dashboard lives in the repo-root ``dashboard/`` folder, but the absolute
    location differs between running locally from ``backend/`` and running inside
    the Docker image (where the backend is flattened into ``/app``). We try a few
    well-known candidates and allow an explicit ``DASHBOARD_DIR`` override so the
    SPA is always found regardless of how the app is deployed.
    """
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "dashboard",  # local: repo-root/backend/app -> repo-root/dashboard
        here.parents[1] / "dashboard",  # docker: /app/app -> /app/dashboard
        Path("/app/dashboard"),
        Path.cwd() / "dashboard",
    ]
    override = os.environ.get("DASHBOARD_DIR")
    if override:
        candidates.insert(0, Path(override))
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


async def _log_outbound_ip() -> None:
    """Log the server's public outbound IP at boot (best-effort).

    Handy for confirming which egress IP this instance is using when allowlisting
    with a third party (e.g. Eneba). NOTE: this only reveals the *single* IP a
    request happened to exit through — on Render the service may use any address
    within its region's fixed outbound range, so the authoritative list is the
    Render dashboard's `Connect -> Outbound` tab. Use this log only as a sanity
    check, and whitelist the full range with the provider.

    Runs only when ``LOG_OUTBOUND_IP`` is enabled and is launched as a detached
    background task (never awaited during startup), so a stalled lookup on an
    egress-restricted host can never delay or fail boot.
    """
    import httpx

    services = ("https://api.ipify.org", "https://ifconfig.me/ip")
    for url in services:
        try:
            async with httpx.AsyncClient(
                timeout=3.0, proxy=settings.outbound_proxy
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                ip = resp.text.strip()
            if ip:
                log.info("app.outbound_ip", outbound_ip=ip, source=url)
                return
        except Exception as exc:  # noqa: BLE001 — never block startup
            log.warning("app.outbound_ip_lookup_failed", source=url, error=str(exc))
    log.warning("app.outbound_ip_unavailable")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Application start-up & shut-down hooks."""
    log.info(
        "app.starting",
        environment=settings.APP_ENV,
        version=settings.APP_VERSION,
    )

    # Best-effort, opt-in, and fully non-blocking: surface the public outbound
    # IP in the logs (for allowlisting). Launched detached so it can NEVER delay
    # or crash startup, even when egress is restricted (Render before a static
    # IP/proxy exists). Enable with LOG_OUTBOUND_IP=true when you need it.
    if settings.APP_ENV != "test" and settings.LOG_OUTBOUND_IP:
        import asyncio

        # Keep a reference so the task isn't GC'd mid-flight; _log_outbound_ip
        # swallows all errors internally, so it never needs result retrieval.
        _ip_task = asyncio.create_task(_log_outbound_ip())  # noqa: RUF006

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
    static_dir = _find_dashboard_dir()
    if static_dir is not None and static_dir.is_dir():
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
