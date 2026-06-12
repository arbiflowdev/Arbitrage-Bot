"""Dashboard summary endpoint (admin only)."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.dependencies import CurrentAdmin, SessionDep
from app.schemas.dashboard import DashboardSummary
from app.services.dashboard_service import DashboardService

router = APIRouter(tags=["dashboard"])


@router.get(
    "/dashboard/summary",
    response_model=DashboardSummary,
    summary="Aggregated KPIs for the dashboard overview",
)
async def dashboard_summary(_: CurrentAdmin, session: SessionDep) -> DashboardSummary:
    return DashboardSummary(**await DashboardService(session).summary())
