"""SKU mapping repository."""

from __future__ import annotations

from sqlalchemy import select

from app.models.sku_mapping import SkuMapping
from app.repositories.base import BaseRepository


class SkuMappingRepository(BaseRepository[SkuMapping]):
    model = SkuMapping

    async def get_by_marketplace_sku(
        self, marketplace: str, marketplace_sku: str
    ) -> SkuMapping | None:
        stmt = select(SkuMapping).where(
            SkuMapping.marketplace == marketplace,
            SkuMapping.marketplace_sku == marketplace_sku,
        )
        return await self.session.scalar(stmt)

    async def list_for_product(self, product_id: int) -> list[SkuMapping]:
        stmt = select(SkuMapping).where(SkuMapping.product_id == product_id)
        result = await self.session.scalars(stmt)
        return list(result.all())
