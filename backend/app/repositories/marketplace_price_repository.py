"""Repository for latest marketplace prices."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.models.marketplace_price import MarketplacePrice
from app.repositories.base import BaseRepository


class MarketplacePriceRepository(BaseRepository[MarketplacePrice]):
    model = MarketplacePrice

    async def get_by_sku(
        self, provider: str, marketplace_sku: str
    ) -> MarketplacePrice | None:
        stmt = select(MarketplacePrice).where(
            MarketplacePrice.provider == provider,
            MarketplacePrice.marketplace_sku == marketplace_sku,
        )
        return await self.session.scalar(stmt)

    async def list_by_provider(
        self, provider: str, *, limit: int = 50, offset: int = 0
    ) -> list[MarketplacePrice]:
        stmt = (
            select(MarketplacePrice)
            .where(MarketplacePrice.provider == provider)
            .order_by(MarketplacePrice.marketplace_sku)
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def upsert(
        self, provider: str, marketplace_sku: str, values: dict[str, Any]
    ) -> MarketplacePrice:
        """Insert a new price row or update the existing one in place."""
        existing = await self.get_by_sku(provider, marketplace_sku)
        if existing is None:
            existing = MarketplacePrice(
                provider=provider, marketplace_sku=marketplace_sku, **values
            )
            self.session.add(existing)
        else:
            for key, value in values.items():
                setattr(existing, key, value)
        await self.session.flush()
        return existing
