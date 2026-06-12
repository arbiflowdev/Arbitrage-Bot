"""Persisted log / error endpoints (admin only)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.dependencies import CurrentAdmin, SessionDep
from app.models.log import LogLevel
from app.repositories.log_repository import LogRepository
from app.schemas.dashboard import LogRead

router = APIRouter(tags=["logs"])


@router.get("/logs", response_model=list[LogRead], summary="List recent log events")
async def list_logs(
    _: CurrentAdmin,
    session: SessionDep,
    level: Annotated[LogLevel | None, Query()] = None,
    source: Annotated[str | None, Query()] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[LogRead]:
    rows = await LogRepository(session).list_recent(
        level=level, source=source, limit=limit, offset=offset
    )
    return [LogRead.model_validate(r) for r in rows]
