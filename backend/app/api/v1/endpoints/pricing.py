"""Arbitrage / dynamic-pricing engine endpoints (admin only).

Operators can inspect engine status, trigger a scan on demand (live or as a
dry-run preview), flip the kill-switch, and read the repricing history and
competitor snapshots. The automated 60-second scan runs in the background; these
endpoints are for control and observability.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Query

from app.core.config import settings
from app.core.dependencies import CurrentAdmin, SessionDep
from app.repositories.pricing_snapshot_repository import PricingSnapshotRepository
from app.repositories.repricing_history_repository import (
    RepricingHistoryRepository,
)
from app.schemas.pricing import (
    KillSwitch,
    PricingSnapshotRead,
    PricingStatus,
    RepricingHistoryRead,
    ScanSummary,
)
from app.services.pricing_control import is_engine_enabled, set_engine_enabled
from app.services.pricing_service import PricingService

router = APIRouter(tags=["pricing"])


@router.get(
    "/pricing/status",
    response_model=PricingStatus,
    summary="Current pricing-engine configuration and kill-switch state",
)
async def pricing_status(_: CurrentAdmin) -> PricingStatus:
    return PricingStatus(
        enabled=await is_engine_enabled(),
        dry_run=settings.PRICING_DRY_RUN,
        mode=settings.MARKETPLACE_MODE,
        scan_interval_seconds=settings.PRICING_SCAN_INTERVAL_SECONDS,
        base_currency=settings.BASE_CURRENCY,
        min_profit_absolute=settings.PRICING_MIN_PROFIT_ABSOLUTE,
        min_profit_margin_percent=settings.PRICING_MIN_PROFIT_MARGIN_PERCENT,
        undercut_amount=settings.PRICING_UNDERCUT_AMOUNT,
        anomaly_drop=settings.PRICING_ANOMALY_DROP,
    )


@router.post(
    "/pricing/scan",
    response_model=ScanSummary,
    summary="Run one repricing scan now (live unless dry_run=true)",
)
async def run_scan(
    _: CurrentAdmin,
    session: SessionDep,
    provider: Annotated[str | None, Query(description="Limit to one provider.")] = None,
    dry_run: Annotated[
        bool | None,
        Query(description="Override the configured dry-run mode for this run."),
    ] = None,
) -> ScanSummary:
    return await PricingService(session).scan(provider=provider, dry_run=dry_run)


@router.post(
    "/pricing/preview",
    response_model=ScanSummary,
    summary="Preview repricing decisions without pushing any price changes",
)
async def preview_scan(
    _: CurrentAdmin,
    session: SessionDep,
    provider: Annotated[str | None, Query(description="Limit to one provider.")] = None,
) -> ScanSummary:
    return await PricingService(session).scan(provider=provider, dry_run=True)


@router.post(
    "/pricing/kill-switch",
    response_model=PricingStatus,
    summary="Enable or disable all automated repricing instantly",
)
async def toggle_kill_switch(
    _: CurrentAdmin,
    payload: Annotated[KillSwitch, Body()],
) -> PricingStatus:
    enabled = await set_engine_enabled(payload.enabled)
    return PricingStatus(
        enabled=enabled,
        dry_run=settings.PRICING_DRY_RUN,
        mode=settings.MARKETPLACE_MODE,
        scan_interval_seconds=settings.PRICING_SCAN_INTERVAL_SECONDS,
        base_currency=settings.BASE_CURRENCY,
        min_profit_absolute=settings.PRICING_MIN_PROFIT_ABSOLUTE,
        min_profit_margin_percent=settings.PRICING_MIN_PROFIT_MARGIN_PERCENT,
        undercut_amount=settings.PRICING_UNDERCUT_AMOUNT,
        anomaly_drop=settings.PRICING_ANOMALY_DROP,
    )


@router.get(
    "/repricing-history",
    response_model=list[RepricingHistoryRead],
    summary="Recent repricing decisions (most recent first)",
)
async def list_repricing_history(
    _: CurrentAdmin,
    session: SessionDep,
    provider: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[RepricingHistoryRead]:
    rows = await RepricingHistoryRepository(session).list_recent(
        provider, limit=limit, offset=offset
    )
    return [RepricingHistoryRead.model_validate(r) for r in rows]


@router.get(
    "/pricing-snapshots",
    response_model=list[PricingSnapshotRead],
    summary="Recent competitor-price snapshots (most recent first)",
)
async def list_pricing_snapshots(
    _: CurrentAdmin,
    session: SessionDep,
    provider: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[PricingSnapshotRead]:
    rows = await PricingSnapshotRepository(session).list_recent(
        provider, limit=limit, offset=offset
    )
    return [PricingSnapshotRead.model_validate(r) for r in rows]
