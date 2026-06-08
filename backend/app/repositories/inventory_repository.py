"""Inventory data access, including the atomic "claim next available" query."""

from __future__ import annotations

from sqlalchemy import func, select

from app.models.inventory import Inventory, InventoryStatus
from app.repositories.base import BaseRepository


class InventoryRepository(BaseRepository[Inventory]):
    model = Inventory

    @property
    def _is_postgres(self) -> bool:
        bind = self.session.bind
        return bool(bind is not None and bind.dialect.name == "postgresql")

    async def claim_one_available(self, product_id: int) -> Inventory | None:
        """Return the next AVAILABLE row for a product, row-locked.

        On PostgreSQL this uses ``FOR UPDATE SKIP LOCKED`` so concurrent workers
        each grab a *different* row without blocking. On SQLite (tests) the lock
        clause is omitted; correctness there relies on the per-order Redis/DB
        lock held by the fulfillment orchestrator.
        """
        stmt = (
            select(Inventory)
            .where(
                Inventory.product_id == product_id,
                Inventory.status == InventoryStatus.AVAILABLE,
            )
            .order_by(Inventory.id)
            .limit(1)
        )
        if self._is_postgres:
            stmt = stmt.with_for_update(skip_locked=True)
        return await self.session.scalar(stmt)

    async def count_status(self, product_id: int, status: InventoryStatus) -> int:
        result = await self.session.scalar(
            select(func.count())
            .select_from(Inventory)
            .where(
                Inventory.product_id == product_id,
                Inventory.status == status,
            )
        )
        return int(result or 0)

    async def list_for_product(
        self,
        product_id: int,
        *,
        status: InventoryStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Inventory]:
        stmt = select(Inventory).where(Inventory.product_id == product_id)
        if status is not None:
            stmt = stmt.where(Inventory.status == status)
        stmt = stmt.order_by(Inventory.id).limit(limit).offset(offset)
        result = await self.session.scalars(stmt)
        return list(result.all())
