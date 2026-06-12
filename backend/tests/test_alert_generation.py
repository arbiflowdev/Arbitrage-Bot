"""Fulfillment raises alerts on failure and awaiting-stock."""

from __future__ import annotations

import pytest
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.inventory import Inventory
from app.models.order import Order, OrderStatus
from app.models.product import Product
from app.models.sku_mapping import SkuMapping
from app.services.alert_service import AlertService
from app.services.fulfillment_service import FulfillmentService


async def _open_alert_types() -> set[str]:
    async with AsyncSessionLocal() as s:
        rows = await AlertService(s).list(AlertStatus.OPEN, limit=100)
        return {r.type.value for r in rows}


@pytest.mark.asyncio
async def test_failed_order_raises_alert() -> None:
    async with AsyncSessionLocal() as s:
        for m in (Alert, Inventory, Order, SkuMapping, Product):
            await s.execute(delete(m))
        # Order with no product mapped -> _fail() path.
        order = Order(
            provider="kinguin", external_order_id="AG-FAIL-1",
            marketplace_sku="NOPE", product_id=None, status=OrderStatus.RECEIVED,
        )
        s.add(order)
        await s.commit()
        oid = order.id
    async with AsyncSessionLocal() as s:
        result = await FulfillmentService(s).fulfill(oid)
        assert result.status == "failed"
    assert AlertType.ORDER_FAILED.value in await _open_alert_types()


@pytest.mark.asyncio
async def test_awaiting_stock_raises_alert() -> None:
    async with AsyncSessionLocal() as s:
        for m in (Alert, Inventory, Order, SkuMapping, Product):
            await s.execute(delete(m))
        product = Product(name="NoStock", internal_sku="NS-1")
        s.add(product)
        await s.flush()
        pid = product.id
        s.add(SkuMapping(product_id=pid, marketplace="kinguin", marketplace_sku="NS-K"))
        order = Order(
            provider="kinguin", external_order_id="AG-AWAIT-1",
            marketplace_sku="NS-K", product_id=pid, status=OrderStatus.RECEIVED,
        )
        s.add(order)
        await s.commit()
        oid = order.id
    async with AsyncSessionLocal() as s:
        # No inventory + no other marketplace price -> SourcingUnavailable -> AWAITING_STOCK
        await FulfillmentService(s).fulfill(oid)
    assert AlertType.AWAITING_STOCK.value in await _open_alert_types()
