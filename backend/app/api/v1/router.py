"""Top-level v1 router that aggregates all endpoint modules."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import (
    alerts,
    auth,
    dashboard,
    fulfillment,
    health,
    logs,
    marketplaces,
    pricing,
    products,
    settings,
    system,
    users,
    webhooks,
)

api_router_v1 = APIRouter(prefix="/v1")
api_router_v1.include_router(health.router)
api_router_v1.include_router(auth.router)
api_router_v1.include_router(settings.router)
api_router_v1.include_router(users.router)
api_router_v1.include_router(products.router)
api_router_v1.include_router(alerts.router)
api_router_v1.include_router(logs.router)
api_router_v1.include_router(system.router)
api_router_v1.include_router(dashboard.router)
api_router_v1.include_router(marketplaces.router)
api_router_v1.include_router(pricing.router)
api_router_v1.include_router(fulfillment.router)
api_router_v1.include_router(webhooks.router)
