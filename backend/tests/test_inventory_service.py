"""Integration tests for InventoryService (SQLite)."""

from __future__ import annotations

import pytest
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.inventory import Inventory, InventoryStatus
from app.models.product import Product
from app.services.inventory_service import InventoryService


async def _fresh_product() -> int:
    async with AsyncSessionLocal() as s:
        await s.execute(delete(Inventory))
        await s.execute(delete(Product))
        await s.commit()
        product = Product(name="Stock Game", internal_sku="STK-1")
        s.add(product)
        await s.flush()
        pid = product.id
        await s.commit()
        return pid


@pytest.mark.asyncio
async def test_upload_txt_creates_available_inventory() -> None:
    pid = await _fresh_product()
    async with AsyncSessionLocal() as s:
        summary = await InventoryService(s).upload(
            pid, "AAA-1\nAAA-2\nAAA-2\n\nAAA-3\n", "txt"
        )
        await s.commit()

    assert summary.added == 3
    assert summary.duplicates == 1
    assert summary.skipped == 1

    async with AsyncSessionLocal() as s:
        count = await InventoryService(s).available_count(pid)
    assert count == 3


@pytest.mark.asyncio
async def test_reserve_one_claims_distinct_available_items() -> None:
    pid = await _fresh_product()
    async with AsyncSessionLocal() as s:
        await InventoryService(s).upload(pid, "K1\nK2\n", "txt")
        await s.commit()

    async with AsyncSessionLocal() as s:
        svc = InventoryService(s)
        first = await svc.reserve_one(pid, order_id=101)
        second = await svc.reserve_one(pid, order_id=102)
        await s.commit()
        assert first is not None and second is not None
        assert first.id != second.id
        assert first.status is InventoryStatus.RESERVED
        assert first.reserved_order_id == 101


@pytest.mark.asyncio
async def test_reserve_one_returns_none_when_empty() -> None:
    pid = await _fresh_product()
    async with AsyncSessionLocal() as s:
        reserved = await InventoryService(s).reserve_one(pid, order_id=1)
    assert reserved is None


@pytest.mark.asyncio
async def test_release_returns_item_to_available() -> None:
    pid = await _fresh_product()
    async with AsyncSessionLocal() as s:
        await InventoryService(s).upload(pid, "K1\n", "txt")
        await s.commit()
    async with AsyncSessionLocal() as s:
        svc = InventoryService(s)
        item = await svc.reserve_one(pid, order_id=5)
        await s.commit()
        assert item is not None
        await svc.release(item.id)
        await s.commit()
    async with AsyncSessionLocal() as s:
        assert await InventoryService(s).available_count(pid) == 1


@pytest.mark.asyncio
async def test_mark_sold_transitions_status() -> None:
    pid = await _fresh_product()
    async with AsyncSessionLocal() as s:
        await InventoryService(s).upload(pid, "K1\n", "txt")
        await s.commit()
    async with AsyncSessionLocal() as s:
        svc = InventoryService(s)
        item = await svc.reserve_one(pid, order_id=9)
        await s.commit()
        sold = await svc.mark_sold(item.id)
        await s.commit()
        assert sold.status is InventoryStatus.SOLD
        assert sold.sold_at is not None
    async with AsyncSessionLocal() as s:
        assert await InventoryService(s).available_count(pid) == 0
