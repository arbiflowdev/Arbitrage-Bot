"""Alert repository — dashboard operational alerts."""

from __future__ import annotations

from sqlalchemy import func, select

from app.models.alert import Alert, AlertSeverity, AlertStatus
from app.repositories.base import BaseRepository


class AlertRepository(BaseRepository[Alert]):
    model = Alert

    async def get_open_by_dedupe(self, dedupe_key: str) -> Alert | None:
        stmt = (
            select(Alert)
            .where(Alert.dedupe_key == dedupe_key)
            .where(Alert.status == AlertStatus.OPEN)
            .order_by(Alert.id.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def list_by_status(
        self, status: AlertStatus | None, *, limit: int = 50, offset: int = 0
    ) -> list[Alert]:
        stmt = select(Alert).order_by(Alert.id.desc()).limit(limit).offset(offset)
        if status is not None:
            stmt = stmt.where(Alert.status == status)
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def count_open_by_severity(self) -> dict[str, int]:
        stmt = (
            select(Alert.severity, func.count())
            .where(Alert.status == AlertStatus.OPEN)
            .group_by(Alert.severity)
        )
        rows = await self.session.execute(stmt)
        counts = {s.value: 0 for s in AlertSeverity}
        for severity, count in rows.all():
            key = severity.value if hasattr(severity, "value") else str(severity)
            counts[key] = int(count)
        return counts
