"""Multi-quantity fulfillment: an order for N units must deliver N codes.

Regression tests for the production bug where a qty>1 order delivered exactly
one code and was then marked DELIVERED, permanently stranding the remaining
units (the idempotency guard blocked any retry). Fulfillment is now per-unit,
tracked in ``order_items``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal
from app.models.inventory import Inventory, InventoryStatus
from app.models.marketplace_price import MarketplacePrice
from app.models.order import Order, OrderStatus
from app.models.order_item import OrderItem, OrderItemStatus
from app.models.product import Product
from app.models.sku_mapping import SkuMapping
from app.models.transaction import Transaction
from app.models.wallet_balance import WalletBalance
from app.services.currency_service import CurrencyService
from app.services.fulfillment_service import FulfillmentService
from app.services.inventory_service import InventoryService

STATIC_RATES = {"EUR": Decimal("1"), "USD": Decimal("1.20")}


def _currency() -> CurrencyService:
    return CurrencyService(static_rates=STATIC_RATES)


async def _wipe() -> None:
    async with AsyncSessionLocal() as s:
        for model in (
            Transaction,
            WalletBalance,
            OrderItem,
            Inventory,
            Order,
            MarketplacePrice,
            SkuMapping,
            Product,
        ):
            await s.execute(delete(model))
        await s.commit()


async def _product() -> int:
    async with AsyncSessionLocal() as s:
        product = Product(name="Multi Game", internal_sku="MUL-1")
        s.add(product)
        await s.flush()
        pid = product.id
        s.add(SkuMapping(product_id=pid, marketplace="kinguin", marketplace_sku="K-1"))
        await s.commit()
        return pid


async def _order(pid: int, *, quantity: int, ext: str = "O-MULTI") -> int:
    async with AsyncSessionLocal() as s:
        order = Order(
            provider="kinguin",
            external_order_id=ext,
            marketplace_sku="K-1",
            product_id=pid,
            quantity=quantity,
            total=Decimal("20.00"),
            currency="EUR",
            status=OrderStatus.RECEIVED,
        )
        s.add(order)
        await s.flush()
        oid = order.id
        await s.commit()
        return oid


async def _sold_count() -> int:
    async with AsyncSessionLocal() as s:
        return int(
            await s.scalar(
                select(func.count())
                .select_from(Inventory)
                .where(Inventory.status == InventoryStatus.SOLD)
            )
        )


@pytest.mark.asyncio
async def test_qty_two_delivers_both_codes() -> None:
    await _wipe()
    pid = await _product()
    async with AsyncSessionLocal() as s:
        await InventoryService(s).upload(pid, "CODE-A\nCODE-B\n", "txt")
        await s.commit()
    oid = await _order(pid, quantity=2)

    async with AsyncSessionLocal() as s:
        result = await FulfillmentService(s, currency=_currency()).fulfill(oid)
        assert result.delivered is True

    # Both codes must be consumed and the order fully delivered.
    assert await _sold_count() == 2
    async with AsyncSessionLocal() as s:
        order = await s.get(Order, oid)
        assert order.status is OrderStatus.DELIVERED
        items = (
            await s.execute(select(OrderItem).where(OrderItem.order_id == oid))
        ).scalars().all()
        assert len(items) == 2
        assert all(i.status is OrderItemStatus.DELIVERED for i in items)


@pytest.mark.asyncio
async def test_qty_two_partial_then_completes_on_restock() -> None:
    """One code in stock, no JIT source: deliver 1, await stock for the 2nd,
    then finish once the missing code is uploaded — never re-delivering the
    first."""
    await _wipe()
    pid = await _product()
    async with AsyncSessionLocal() as s:
        await InventoryService(s).upload(pid, "ONLY-ONE\n", "txt")
        await s.commit()
    oid = await _order(pid, quantity=2)

    # First pass: only one unit can be filled (no g2g source mapping/funds).
    async with AsyncSessionLocal() as s:
        result = await FulfillmentService(s, currency=_currency()).fulfill(oid)
        assert result.delivered is False

    assert await _sold_count() == 1
    async with AsyncSessionLocal() as s:
        order = await s.get(Order, oid)
        assert order.status is OrderStatus.AWAITING_STOCK
        assert order.last_error
        items = (
            await s.execute(
                select(OrderItem)
                .where(OrderItem.order_id == oid)
                .order_by(OrderItem.unit_index)
            )
        ).scalars().all()
        delivered = [i for i in items if i.status is OrderItemStatus.DELIVERED]
        assert len(delivered) == 1

    # Restock the missing unit; the retry completes the order.
    async with AsyncSessionLocal() as s:
        await InventoryService(s).upload(pid, "SECOND-ONE\n", "txt")
        await s.commit()
    async with AsyncSessionLocal() as s:
        result = await FulfillmentService(s, currency=_currency()).fulfill(oid)
        assert result.delivered is True

    assert await _sold_count() == 2  # first code was NOT double-consumed
    async with AsyncSessionLocal() as s:
        order = await s.get(Order, oid)
        assert order.status is OrderStatus.DELIVERED


@pytest.mark.asyncio
async def test_delivered_multiqty_order_is_not_redelivered() -> None:
    await _wipe()
    pid = await _product()
    async with AsyncSessionLocal() as s:
        await InventoryService(s).upload(pid, "A1\nA2\nA3\n", "txt")
        await s.commit()
    oid = await _order(pid, quantity=2)

    async with AsyncSessionLocal() as s:
        await FulfillmentService(s, currency=_currency()).fulfill(oid)
    async with AsyncSessionLocal() as s:
        second = await FulfillmentService(s, currency=_currency()).fulfill(oid)
        assert second.delivered is False  # already delivered -> no-op

    # Exactly two codes consumed; the spare stays available.
    assert await _sold_count() == 2
    async with AsyncSessionLocal() as s:
        available = int(
            await s.scalar(
                select(func.count())
                .select_from(Inventory)
                .where(Inventory.status == InventoryStatus.AVAILABLE)
            )
        )
        assert available == 1
