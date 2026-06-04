"""Repository for repricing-decision history."""

from __future__ import annotations

from sqlalchemy import select

from app.models.repricing_history import RepricingHistory
from app.repositories.base import BaseRepository


class RepricingHistoryRepository(BaseRepository[RepricingHistory]):
    model = RepricingHistory

    async def list_recent(
        self,
        provider: str | None = None,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RepricingHistory]:
        stmt = select(RepricingHistory)
        if provider is not None:
            stmt = stmt.where(RepricingHistory.provider == provider)
        stmt = (
            stmt.order_by(RepricingHistory.id.desc()).limit(limit).offset(offset)
        )
        result = await self.session.scalars(stmt)
        return list(result.all())
