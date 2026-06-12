"""Dashboard summary aggregator — one call powers the Overview page.

The independent reads run concurrently (each on its own session/connection)
so the endpoint's latency is the slowest single query, not the sum of them —
a big win against a remote database.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.inventory import Inventory, InventoryStatus
from app.models.order import Order, OrderStatus
from app.models.transaction import Transaction, TransactionType
from app.models.wallet_balance import WalletBalance
from app.repositories.alert_repository import AlertRepository
from app.services.fulfillment_control import is_fulfillment_enabled
from app.services.pricing_control import is_engine_enabled
from app.utils.datetime import utcnow


class DashboardService:
    def __init__(self, session: AsyncSession | None = None) -> None:
        # Kept for call-site compatibility; the parallel reads open their own
        # short-lived sessions so they can run concurrently.
        self.session = session

    async def summary(self) -> dict:
        (
            orders,
            today,
            inventory_available,
            wallets_tuple,
            alerts,
            pricing_enabled,
            fulfillment_enabled,
        ) = await asyncio.gather(
            self._orders_by_status(),
            self._today(),
            self._inventory_available(),
            self._wallets(),
            self._alerts(),
            is_engine_enabled(),
            is_fulfillment_enabled(),
        )
        revenue_today, delivered_today = today
        wallets, wallet_total = wallets_tuple
        return {
            "orders": orders,
            "revenue_today": revenue_today,
            "delivered_today": delivered_today,
            "inventory_available": inventory_available,
            "wallet_total": wallet_total,
            "wallets": wallets,
            "alerts": alerts,
            "engine": {
                "pricing_enabled": pricing_enabled,
                "fulfillment_enabled": fulfillment_enabled,
                "mode": settings.MARKETPLACE_MODE,
                "dry_run": settings.PRICING_DRY_RUN,
            },
        }

    async def _orders_by_status(self) -> dict[str, int]:
        async with AsyncSessionLocal() as s:
            rows = await s.execute(select(Order.status, func.count()).group_by(Order.status))
            counts = {st.value: 0 for st in OrderStatus}
            for status_val, count in rows.all():
                key = status_val.value if hasattr(status_val, "value") else str(status_val)
                counts[key] = int(count)
            return counts

    async def _today(self) -> tuple[Decimal, int]:
        start = datetime.combine(utcnow().date(), time.min, tzinfo=utcnow().tzinfo)
        async with AsyncSessionLocal() as s:
            revenue = await s.scalar(
                select(func.coalesce(func.sum(Transaction.amount), 0))
                .where(Transaction.type == TransactionType.SALE_REVENUE)
                .where(Transaction.created_at >= start)
            )
            delivered = await s.scalar(
                select(func.count())
                .select_from(Order)
                .where(Order.status == OrderStatus.DELIVERED)
                .where(Order.delivered_at >= start)
            )
        return Decimal(str(revenue or 0)), int(delivered or 0)

    async def _inventory_available(self) -> int:
        async with AsyncSessionLocal() as s:
            value = await s.scalar(
                select(func.count())
                .select_from(Inventory)
                .where(Inventory.status == InventoryStatus.AVAILABLE)
            )
        return int(value or 0)

    async def _wallets(self) -> tuple[list[dict], Decimal]:
        async with AsyncSessionLocal() as s:
            rows = await s.scalars(select(WalletBalance))
            wallets = list(rows.all())
        out = [
            {"provider": w.provider, "currency": w.currency, "balance": str(w.balance)}
            for w in wallets
        ]
        total = sum((Decimal(w.balance) for w in wallets), Decimal("0"))
        return out, total

    async def _alerts(self) -> dict[str, int]:
        async with AsyncSessionLocal() as s:
            return await AlertRepository(s).count_open_by_severity()
