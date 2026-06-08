"""Integration tests for OrderIntakeService idempotency (SQLite)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal
from app.models.order import Order, OrderStatus
from app.models.product import Product
from app.models.sku_mapping import SkuMapping
from app.services.order_intake_service import OrderIntakeService


async def _seed_product() -> int:
    async with AsyncSessionLocal() as s:
        await s.execute(delete(Order))
        await s.execute(delete(SkuMapping))
        await s.execute(delete(Product))
        await s.commit()
        product = Product(name="Sold Game", internal_sku="SOLD-1")
        s.add(product)
        await s.flush()
        pid = product.id
        s.add(SkuMapping(product_id=pid, marketplace="kinguin", marketplace_sku="K-9"))
        await s.commit()
        return pid


@pytest.mark.asyncio
async def test_ingest_creates_received_order_with_resolved_product() -> None:
    pid = await _seed_product()
    async with AsyncSessionLocal() as s:
        order, created = await OrderIntakeService(s).ingest(
            "kinguin", "EXT-1", "K-9", total=Decimal("19.99"), currency="EUR"
        )
        await s.commit()
        assert created is True
        assert order.status is OrderStatus.RECEIVED
        assert order.product_id == pid


@pytest.mark.asyncio
async def test_ingest_is_idempotent_on_duplicate_external_id() -> None:
    await _seed_product()
    async with AsyncSessionLocal() as s:
        await OrderIntakeService(s).ingest("kinguin", "EXT-DUP", "K-9")
        await s.commit()
    async with AsyncSessionLocal() as s:
        order, created = await OrderIntakeService(s).ingest("kinguin", "EXT-DUP", "K-9")
        await s.commit()
        assert created is False

    async with AsyncSessionLocal() as s:
        count = await s.scalar(
            select(func.count()).select_from(Order).where(
                Order.external_order_id == "EXT-DUP"
            )
        )
        assert count == 1
