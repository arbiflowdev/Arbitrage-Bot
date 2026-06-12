"""Persist notable operational events to the queryable ``logs`` table.

Structured logs still go to stdout; this records the operationally-relevant
events the dashboard's Logs page surfaces. Best-effort: a logging failure must
never break the caller's primary work.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.log import LogLevel
from app.repositories.log_repository import LogRepository

log = get_logger(__name__)


async def record_event(
    session: AsyncSession,
    level: LogLevel,
    source: str,
    message: str,
    context: dict[str, Any] | None = None,
) -> None:
    try:
        await LogRepository(session).record(
            level=level, source=source, message=message[:2000], context=context
        )
    except Exception as exc:  # noqa: BLE001 — logging must not break callers
        log.warning("event_log.record_failed", error=str(exc))
