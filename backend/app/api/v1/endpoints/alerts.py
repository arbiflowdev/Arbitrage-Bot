"""Operational alert endpoints (admin only)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.core.dependencies import CurrentAdmin, SessionDep
from app.models.alert import AlertStatus
from app.schemas.dashboard import AlertRead, AlertSummary
from app.services.alert_service import AlertService

router = APIRouter(tags=["alerts"])


@router.get("/alerts", response_model=list[AlertRead], summary="List alerts")
async def list_alerts(
    _: CurrentAdmin,
    session: SessionDep,
    status_filter: Annotated[AlertStatus | None, Query(alias="status")] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AlertRead]:
    rows = await AlertService(session).list(status_filter, limit=limit, offset=offset)
    return [AlertRead.model_validate(r) for r in rows]


@router.get("/alerts/summary", response_model=AlertSummary, summary="Open alert counts")
async def alerts_summary(_: CurrentAdmin, session: SessionDep) -> AlertSummary:
    counts = await AlertService(session).summary()
    return AlertSummary(**counts)


@router.post(
    "/alerts/{alert_id}/acknowledge",
    response_model=AlertRead,
    summary="Acknowledge an alert",
)
async def acknowledge_alert(
    _: CurrentAdmin, session: SessionDep, alert_id: int
) -> AlertRead:
    alert = await AlertService(session).acknowledge(alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    await session.commit()
    return AlertRead.model_validate(alert)


@router.post(
    "/alerts/{alert_id}/resolve",
    response_model=AlertRead,
    summary="Resolve an alert",
)
async def resolve_alert(
    _: CurrentAdmin, session: SessionDep, alert_id: int
) -> AlertRead:
    alert = await AlertService(session).resolve(alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    await session.commit()
    return AlertRead.model_validate(alert)
