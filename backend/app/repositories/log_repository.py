"""Log repository — persisted application events for the admin UI."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.models.log import Log, LogLevel
from app.repositories.base import BaseRepository


class LogRepository(BaseRepository[Log]):
    model = Log

    async def record(
        self,
        *,
        level: LogLevel,
        source: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> Log:
        log = Log(level=level, source=source, message=message, context=context)
        return await self.add(log)

    async def list_recent(self, *, limit: int = 100) -> list[Log]:
        stmt = select(Log).order_by(Log.created_at.desc()).limit(limit)
        result = await self.session.scalars(stmt)
        return list(result.all())
