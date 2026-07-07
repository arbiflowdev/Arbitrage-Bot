"""Integration tests for the FulfillmentService orchestrator (SQLite, mock)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal
from app.integrations.base import DeliveryResult
from app.integrations.mock import MockAdapter
from app.models.inventory import Inventory, InventoryStatus
from app.models.marketplace_price import MarketplacePrice
from app.models.order import FulfillmentSource, Order, OrderStatus
from app.models.order_item import OrderItem
from app.models.product import Product
from app.models.sku_mapping import SkuMapping
from app.models.transaction import Transaction
from app.models.wallet_balance import WalletBalance
from app.services.currency_service import CurrencyService
from app.services.fulfillment_service import FulfillmentService
from app.services.inventory_service import InventoryService
from app.services.wallet_service import WalletService

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


async def _order(pid: int, *, ext: str = "O-1") -> int:
    async with AsyncSessionLocal() as s:
        order = Order(
            provider="kinguin",
            external_order_id=ext,
            marketplace_sku="K-1",
            product_id=pid,
            quantity=1,
            total=Decimal("20.00"),
            currency="EUR",
            status=OrderStatus.RECEIVED,
        )
        s.add(order)
        await s.flush()
        oid = order.id
        await s.commit()
        return oid


async def _product() -> int:
    async with AsyncSessionLocal() as s:
        product = Product(name="Fulfil Game", internal_sku="FUL-1")
        s.add(product)
        await s.flush()
        pid = product.id
        s.add(SkuMapping(product_id=pid, marketplace="kinguin", marketplace_sku="K-1"))
        await s.commit()
        return pid


@pytest.mark.asyncio
async def test_fulfills_from_manual_inventory_first() -> None:
    await _wipe()
    pid = await _product()
    async with AsyncSessionLocal() as s:
        await InventoryService(s).upload(pid, "STOCK-KEY-1\n", "txt")
        await s.commit()
    oid = await _order(pid)

    async with AsyncSessionLocal() as s:
        result = await FulfillmentService(s, currency=_currency()).fulfill(oid)
        assert result.delivered is True

    async with AsyncSessionLocal() as s:
        order = await s.get(Order, oid)
        assert order.status is OrderStatus.DELIVERED
        assert order.fulfillment_source is FulfillmentSource.MANUAL
        assert order.delivered_at is not None
        inv = (await s.execute(select(Inventory))).scalar_one()
        assert inv.status is InventoryStatus.SOLD


@pytest.mark.asyncio
async def test_falls_back_to_jit_when_no_inventory() -> None:
    await _wipe()
    pid = await _product()
    async with AsyncSessionLocal() as s:
        # A cheaper supplier on another marketplace + funded wallet.
        s.add(
            MarketplacePrice(
                provider="g2g",
                marketplace_sku="G-1",
                product_id=pid,
                currency="EUR",
                price=Decimal("8.00"),
            )
        )
        s.add(SkuMapping(product_id=pid, marketplace="g2g", marketplace_sku="G-1"))
        await WalletService(s).top_up("g2g", "EUR", Decimal("100.00"))
        await s.commit()
    oid = await _order(pid)

    async with AsyncSessionLocal() as s:
        result = await FulfillmentService(s, currency=_currency()).fulfill(oid)
        assert result.delivered is True

    async with AsyncSessionLocal() as s:
        order = await s.get(Order, oid)
        assert order.status is OrderStatus.DELIVERED
        assert order.fulfillment_source is FulfillmentSource.JIT
        # Wallet was debited for the purchase.
        wallet = (
            await s.execute(select(WalletBalance).where(WalletBalance.provider == "g2g"))
        ).scalar_one()
        assert Decimal(wallet.balance) == Decimal("92.00")


@pytest.mark.asyncio
async def test_duplicate_fulfill_does_not_deliver_twice() -> None:
    await _wipe()
    pid = await _product()
    async with AsyncSessionLocal() as s:
        await InventoryService(s).upload(pid, "K-A\nK-B\n", "txt")
        await s.commit()
    oid = await _order(pid)

    async with AsyncSessionLocal() as s:
        await FulfillmentService(s, currency=_currency()).fulfill(oid)
    async with AsyncSessionLocal() as s:
        second = await FulfillmentService(s, currency=_currency()).fulfill(oid)
        assert second.delivered is False  # already delivered -> no-op

    async with AsyncSessionLocal() as s:
        sold = await s.scalar(
            select(func.count()).select_from(Inventory).where(
                Inventory.status == InventoryStatus.SOLD
            )
        )
        assert sold == 1  # only one code ever consumed


@pytest.mark.asyncio
async def test_no_stock_and_underfunded_jit_marks_awaiting_stock() -> None:
    await _wipe()
    pid = await _product()
    async with AsyncSessionLocal() as s:
        s.add(SkuMapping(product_id=pid, marketplace="g2g", marketplace_sku="G-1"))
        s.add(
            MarketplacePrice(
                provider="g2g",
                marketplace_sku="G-1",
                product_id=pid,
                currency="EUR",
                price=Decimal("8.00"),
            )
        )
        await s.commit()  # wallet NOT funded
    oid = await _order(pid)

    async with AsyncSessionLocal() as s:
        result = await FulfillmentService(s, currency=_currency()).fulfill(oid)
        assert result.delivered is False

    async with AsyncSessionLocal() as s:
        order = await s.get(Order, oid)
        assert order.status is OrderStatus.AWAITING_STOCK
        assert order.last_error


@pytest.mark.asyncio
async def test_delivery_failure_releases_reservation_for_retry(monkeypatch) -> None:
    await _wipe()
    pid = await _product()
    async with AsyncSessionLocal() as s:
        await InventoryService(s).upload(pid, "ONLY-KEY\n", "txt")
        await s.commit()
    oid = await _order(pid)

    async def _fail_deliver(self, external_order_id, code, *, marketplace_sku=None):
        return DeliveryResult(success=False, reference=None)

    monkeypatch.setattr(MockAdapter, "deliver", _fail_deliver)

    async with AsyncSessionLocal() as s:
        result = await FulfillmentService(s, currency=_currency()).fulfill(oid)
        assert result.delivered is False

    async with AsyncSessionLocal() as s:
        order = await s.get(Order, oid)
        assert order.status is not OrderStatus.DELIVERED
        assert order.last_error
        # The reserved code was returned to the available pool for a retry.
        inv = (await s.execute(select(Inventory))).scalar_one()
        assert inv.status is InventoryStatus.AVAILABLE
