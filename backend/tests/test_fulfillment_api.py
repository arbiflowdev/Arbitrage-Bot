"""API tests for the Milestone 4 fulfillment endpoints (admin-only)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.inventory import Inventory
from app.models.order import Order
from app.models.product import Product
from app.models.sku_mapping import SkuMapping
from app.models.transaction import Transaction
from app.models.wallet_balance import WalletBalance


async def _seed_product() -> int:
    async with AsyncSessionLocal() as s:
        for model in (Transaction, WalletBalance, Inventory, Order, SkuMapping, Product):
            await s.execute(delete(model))
        await s.commit()
        product = Product(name="API Game", internal_sku="API-1")
        s.add(product)
        await s.flush()
        pid = product.id
        s.add(SkuMapping(product_id=pid, marketplace="kinguin", marketplace_sku="K-1"))
        await s.commit()
        return pid


@pytest.mark.asyncio
async def test_inventory_upload_requires_admin(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/inventory/upload",
        json={"product_id": 1, "format": "txt", "content": "K1"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_uploads_inventory_and_reads_summary(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    pid = await _seed_product()
    up = await client.post(
        "/api/v1/inventory/upload",
        headers=admin_headers,
        json={"product_id": pid, "format": "txt", "content": "K1\nK2\nK2\n"},
    )
    assert up.status_code == 200, up.text
    body = up.json()
    assert body["added"] == 2
    assert body["duplicates"] == 1

    summary = await client.get(
        f"/api/v1/inventory/summary?product_id={pid}", headers=admin_headers
    )
    assert summary.status_code == 200
    assert summary.json()["available"] == 2


@pytest.mark.asyncio
async def test_wallet_top_up_and_list(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    await _seed_product()
    resp = await client.post(
        "/api/v1/wallet/top-up",
        headers=admin_headers,
        json={"provider": "g2g", "currency": "USD", "amount": "150.00"},
    )
    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["balance"]) == Decimal("150.00")

    listing = await client.get("/api/v1/wallet", headers=admin_headers)
    assert listing.status_code == 200
    assert any(w["provider"] == "g2g" for w in listing.json())


@pytest.mark.asyncio
async def test_order_ingest_fulfills_from_stock_and_masks_codes(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    pid = await _seed_product()
    await client.post(
        "/api/v1/inventory/upload",
        headers=admin_headers,
        json={"product_id": pid, "format": "txt", "content": "SECRET-KEY-123\n"},
    )
    ingest = await client.post(
        "/api/v1/orders/ingest",
        headers=admin_headers,
        json={
            "provider": "kinguin",
            "external_order_id": "API-O-1",
            "marketplace_sku": "K-1",
            "total": "20.00",
            "currency": "EUR",
        },
    )
    assert ingest.status_code == 200, ingest.text
    assert ingest.json()["status"] == "delivered"

    inv = await client.get(
        f"/api/v1/inventory?product_id={pid}", headers=admin_headers
    )
    assert inv.status_code == 200
    # The raw code must never be exposed by the API.
    assert all("SECRET-KEY-123" not in item["code_masked"] for item in inv.json())
