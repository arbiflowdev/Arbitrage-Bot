"""System-wide status and kill-switch endpoints (admin only).

The global kill-switch flips both the pricing engine and the fulfillment
pipeline at once — the operator's single "stop everything" control.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body

from app.core.config import settings
from app.core.dependencies import CurrentAdmin
from app.schemas.dashboard import KillSwitchRequest, SystemStatus
from app.services.fulfillment_control import (
    is_fulfillment_enabled,
    set_fulfillment_enabled,
)
from app.services.pricing_control import is_engine_enabled, set_engine_enabled

router = APIRouter(tags=["system"])


@router.get(
    "/system/status",
    response_model=SystemStatus,
    summary="Pricing + fulfillment runtime state",
)
async def system_status(_: CurrentAdmin) -> SystemStatus:
    return SystemStatus(
        pricing_enabled=await is_engine_enabled(),
        fulfillment_enabled=await is_fulfillment_enabled(),
        mode=settings.MARKETPLACE_MODE,
        dry_run=settings.PRICING_DRY_RUN,
    )


@router.post(
    "/system/kill-switch",
    response_model=SystemStatus,
    summary="Enable/disable BOTH pricing and fulfillment at once",
)
async def global_kill_switch(
    _: CurrentAdmin, payload: Annotated[KillSwitchRequest, Body()]
) -> SystemStatus:
    pricing = await set_engine_enabled(payload.enabled)
    fulfillment = await set_fulfillment_enabled(payload.enabled)
    return SystemStatus(
        pricing_enabled=pricing,
        fulfillment_enabled=fulfillment,
        mode=settings.MARKETPLACE_MODE,
        dry_run=settings.PRICING_DRY_RUN,
    )


@router.post(
    "/fulfillment/kill-switch",
    response_model=SystemStatus,
    summary="Enable/disable only the fulfillment pipeline",
)
async def fulfillment_kill_switch(
    _: CurrentAdmin, payload: Annotated[KillSwitchRequest, Body()]
) -> SystemStatus:
    fulfillment = await set_fulfillment_enabled(payload.enabled)
    return SystemStatus(
        pricing_enabled=await is_engine_enabled(),
        fulfillment_enabled=fulfillment,
        mode=settings.MARKETPLACE_MODE,
        dry_run=settings.PRICING_DRY_RUN,
    )
