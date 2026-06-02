"""Repository for marketplace listings."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.models.listing import Listing
from app.repositories.base import BaseRepository


class ListingRepository(BaseRepository[Listing]):
    model = Listing

    async def get_by_sku(self, provider: str, marketplace_sku: str) -> Listing | None:
        stmt = select(Listing).where(
            Listing.provider == provider,
            Listing.marketplace_sku == marketplace_sku,
        )
        return await self.session.scalar(stmt)

    async def list_by_provider(
        self, provider: str | None = None, *, limit: int = 50, offset: int = 0
    ) -> list[Listing]:
        stmt = select(Listing).order_by(Listing.id).limit(limit).offset(offset)
        if provider is not None:
            stmt = stmt.where(Listing.provider == provider)
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def upsert(
        self, provider: str, marketplace_sku: str, values: dict[str, Any]
    ) -> Listing:
        """Insert or update a listing keyed by ``(provider, marketplace_sku)``."""
        existing = await self.get_by_sku(provider, marketplace_sku)
        if existing is None:
            existing = Listing(
                provider=provider, marketplace_sku=marketplace_sku, **values
            )
            self.session.add(existing)
        else:
            for key, value in values.items():
                setattr(existing, key, value)
        await self.session.flush()
        return existing
