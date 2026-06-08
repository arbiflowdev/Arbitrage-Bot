"""An order webhook should ingest the order and trigger fulfillment."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.inventory import Inventory
from app.models.order import Order, OrderStatus
from app.models.product import Product
from app.models.sku_mapping import SkuMapping
from app.services.inventory_service import InventoryService


@pytest.mark.asyncio
async def test_order_webhook_ingests_and_fulfills(client: AsyncClient) -> None:
    async with AsyncSessionLocal() as s:
        for model in (Inventory, Order, SkuMapping, Product):
            await s.execute(delete(model))
        await s.commit()
        product = Product(name="WH Game", internal_sku="WH-1")
        s.add(product)
        await s.flush()
        pid = product.id
        s.add(SkuMapping(product_id=pid, marketplace="kinguin", marketplace_sku="K-1"))
        await InventoryService(s).upload(pid, "WH-KEY-1\n", "txt")
        await s.commit()

    resp = await client.post(
        "/api/v1/webhooks/kinguin",
        json={
            "event_type": "order.paid",
            "id": "WH-ORD-1",
            "marketplace_sku": "K-1",
            "total": 20.0,
            "currency": "EUR",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["received"] is True

    async with AsyncSessionLocal() as s:
        order = (
            await s.execute(
                select(Order).where(Order.external_order_id == "WH-ORD-1")
            )
        ).scalar_one()
        assert order.status is OrderStatus.DELIVERED
