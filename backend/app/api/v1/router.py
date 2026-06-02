"""Top-level v1 router that aggregates all endpoint modules."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    health,
    marketplaces,
    settings,
    webhooks,
)

api_router_v1 = APIRouter(prefix="/v1")
api_router_v1.include_router(health.router)
api_router_v1.include_router(auth.router)
api_router_v1.include_router(settings.router)
api_router_v1.include_router(marketplaces.router)
api_router_v1.include_router(webhooks.router)
