"""Order data access, including dedup lookup and row-locked fetch."""

from __future__ import annotations

from sqlalchemy import select

from app.models.order import Order, OrderStatus
from app.repositories.base import BaseRepository


class OrderRepository(BaseRepository[Order]):
    model = Order

    @property
    def _is_postgres(self) -> bool:
        bind = self.session.bind
        return bool(bind is not None and bind.dialect.name == "postgresql")

    async def get_by_external(
        self, provider: str, external_order_id: str
    ) -> Order | None:
        return await self.session.scalar(
            select(Order).where(
                Order.provider == provider,
                Order.external_order_id == external_order_id,
            )
        )

    async def get_for_update(self, order_id: int) -> Order | None:
        stmt = select(Order).where(Order.id == order_id)
        if self._is_postgres:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def list_by_status(
        self, statuses: list[OrderStatus], *, limit: int = 100
    ) -> list[Order]:
        result = await self.session.scalars(
            select(Order)
            .where(Order.status.in_(statuses))
            .order_by(Order.id)
            .limit(limit)
        )
        return list(result.all())

    async def list_recent(
        self,
        provider: str | None = None,
        *,
        status: OrderStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Order]:
        stmt = select(Order)
        if provider is not None:
            stmt = stmt.where(Order.provider == provider)
        if status is not None:
            stmt = stmt.where(Order.status == status)
        stmt = stmt.order_by(Order.id.desc()).limit(limit).offset(offset)
        result = await self.session.scalars(stmt)
        return list(result.all())
