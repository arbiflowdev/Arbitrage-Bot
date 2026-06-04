"""Repository for cached competitor-price snapshots."""

from __future__ import annotations

from sqlalchemy import select

from app.models.pricing_snapshot import PricingSnapshot
from app.repositories.base import BaseRepository


class PricingSnapshotRepository(BaseRepository[PricingSnapshot]):
    model = PricingSnapshot

    async def list_recent(
        self,
        provider: str | None = None,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PricingSnapshot]:
        stmt = select(PricingSnapshot)
        if provider is not None:
            stmt = stmt.where(PricingSnapshot.provider == provider)
        stmt = (
            stmt.order_by(PricingSnapshot.id.desc()).limit(limit).offset(offset)
        )
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def latest_for(
        self, provider: str, marketplace_sku: str
    ) -> PricingSnapshot | None:
        stmt = (
            select(PricingSnapshot)
            .where(
                PricingSnapshot.provider == provider,
                PricingSnapshot.marketplace_sku == marketplace_sku,
            )
            .order_by(PricingSnapshot.id.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)
