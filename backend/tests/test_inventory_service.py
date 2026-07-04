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
async def test_reupload_skips_codes_already_in_stock() -> None:
    """Re-uploading a code that already exists for the product must NOT create a
    second AVAILABLE row — that silent duplication is what inflated the pushed
    stock (168 real codes advertised as ~1.3k). Only genuinely new codes are
    added; the overlap is reported as duplicates."""
    pid = await _fresh_product()
    async with AsyncSessionLocal() as s:
        await InventoryService(s).upload(pid, "K1\nK2\n", "txt")
        await s.commit()

    async with AsyncSessionLocal() as s:
        summary = await InventoryService(s).upload(pid, "K2\nK3\n", "txt")
        await s.commit()

    assert summary.added == 1  # only K3 is new
    assert summary.duplicates == 1  # K2 already held
    async with AsyncSessionLocal() as s:
        assert await InventoryService(s).available_count(pid) == 3  # K1, K2, K3


@pytest.mark.asyncio
async def test_reupload_does_not_resurrect_sold_code() -> None:
    """A code already SOLD must not be re-added as AVAILABLE on re-upload —
    otherwise the bot would advertise (and could oversell) a spent code."""
    pid = await _fresh_product()
    async with AsyncSessionLocal() as s:
        await InventoryService(s).upload(pid, "SOLD-1\n", "txt")
        await s.commit()
    async with AsyncSessionLocal() as s:
        svc = InventoryService(s)
        item = await svc.reserve_one(pid, order_id=7)
        await s.commit()
        await svc.mark_sold(item.id)
        await s.commit()

    async with AsyncSessionLocal() as s:
        summary = await InventoryService(s).upload(pid, "SOLD-1\n", "txt")
        await s.commit()

    assert summary.added == 0
    assert summary.duplicates == 1
    async with AsyncSessionLocal() as s:
        assert await InventoryService(s).available_count(pid) == 0


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
