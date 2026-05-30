"""Health-check endpoint."""

from __future__ import annotations

import time

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.redis import ping_redis
from app.schemas.health import ComponentHealth, HealthResponse

router = APIRouter(tags=["health"])


async def _check_database() -> ComponentHealth:
    start = time.perf_counter()
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return ComponentHealth(
            status="ok",
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
        )
    except Exception as exc:  # noqa: BLE001
        return ComponentHealth(status="down", error=str(exc))


async def _check_redis() -> ComponentHealth:
    start = time.perf_counter()
    try:
        ok = await ping_redis()
        if not ok:
            return ComponentHealth(status="down", error="PING returned false")
        return ComponentHealth(
            status="ok",
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
        )
    except Exception as exc:  # noqa: BLE001
        return ComponentHealth(status="down", error=str(exc))


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness & dependency health",
)
async def health() -> HealthResponse:
    components = {
        "database": await _check_database(),
        "redis": await _check_redis(),
    }
    overall = "ok" if all(c.status == "ok" for c in components.values()) else "degraded"
    return HealthResponse(
        status=overall,
        app=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.APP_ENV,
        components=components,
    )
