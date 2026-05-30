"""Product repository."""

from __future__ import annotations

from sqlalchemy import select

from app.models.product import Product
from app.repositories.base import BaseRepository


class ProductRepository(BaseRepository[Product]):
    model = Product

    async def get_by_internal_sku(self, internal_sku: str) -> Product | None:
        stmt = select(Product).where(Product.internal_sku == internal_sku)
        return await self.session.scalar(stmt)
