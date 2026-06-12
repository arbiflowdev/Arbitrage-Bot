"""API tests for the Milestone 5 products listing endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.product import Product


async def _seed_products() -> None:
    async with AsyncSessionLocal() as s:
        await s.execute(delete(Product))
        s.add(Product(name="Game A", internal_sku="P5-A"))
        s.add(Product(name="Game B", internal_sku="P5-B"))
        await s.commit()


@pytest.mark.asyncio
async def test_products_requires_admin(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/products")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_lists_products(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    await _seed_products()
    resp = await client.get("/api/v1/products", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    skus = {p["internal_sku"] for p in resp.json()}
    assert {"P5-A", "P5-B"} <= skus
