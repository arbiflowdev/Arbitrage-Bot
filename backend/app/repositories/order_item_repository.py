"""Order-item data access — the per-unit rows a multi-quantity order expands to."""

from __future__ import annotations

from sqlalchemy import func, select

from app.models.order_item import OrderItem
from app.repositories.base import BaseRepository


class OrderItemRepository(BaseRepository[OrderItem]):
    model = OrderItem

    async def list_for_order(self, order_id: int) -> list[OrderItem]:
        result = await self.session.scalars(
            select(OrderItem)
            .where(OrderItem.order_id == order_id)
            .order_by(OrderItem.unit_index)
        )
        return list(result.all())

    async def count_for_order(self, order_id: int) -> int:
        result = await self.session.scalar(
            select(func.count())
            .select_from(OrderItem)
            .where(OrderItem.order_id == order_id)
        )
        return int(result or 0)
