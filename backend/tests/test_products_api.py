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


@pytest.mark.asyncio
async def test_admin_creates_product(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/products",
        headers=admin_headers,
        json={"internal_sku": "NEW-1", "name": "New Game", "platform": "Steam"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["internal_sku"] == "NEW-1"
    assert body["is_active"] is True
    assert isinstance(body["id"], int)


@pytest.mark.asyncio
async def test_create_product_duplicate_sku_conflicts(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    payload = {"internal_sku": "DUP-1", "name": "Dup"}
    first = await client.post("/api/v1/products", headers=admin_headers, json=payload)
    assert first.status_code == 201, first.text
    second = await client.post("/api/v1/products", headers=admin_headers, json=payload)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_update_product(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/v1/products",
        headers=admin_headers,
        json={"internal_sku": "UPD-1", "name": "Before"},
    )
    pid = created.json()["id"]
    resp = await client.patch(
        f"/api/v1/products/{pid}",
        headers=admin_headers,
        json={"name": "After", "is_active": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "After"
    assert resp.json()["is_active"] is False


@pytest.mark.asyncio
async def test_create_list_and_delete_mapping(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/v1/products",
        headers=admin_headers,
        json={"internal_sku": "MAP-1", "name": "Mapped"},
    )
    pid = created.json()["id"]

    made = await client.post(
        f"/api/v1/products/{pid}/mappings",
        headers=admin_headers,
        json={"marketplace": "kinguin", "marketplace_sku": "KGN-MAP-1"},
    )
    assert made.status_code == 201, made.text
    mapping_id = made.json()["id"]
    assert made.json()["marketplace"] == "kinguin"

    listed = await client.get(
        f"/api/v1/products/{pid}/mappings", headers=admin_headers
    )
    assert listed.status_code == 200
    assert any(m["marketplace_sku"] == "KGN-MAP-1" for m in listed.json())

    deleted = await client.delete(
        f"/api/v1/products/{pid}/mappings/{mapping_id}", headers=admin_headers
    )
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_mapping_rejects_unknown_marketplace(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/v1/products",
        headers=admin_headers,
        json={"internal_sku": "MAP-BAD", "name": "BadMap"},
    )
    pid = created.json()["id"]
    resp = await client.post(
        f"/api/v1/products/{pid}/mappings",
        headers=admin_headers,
        json={"marketplace": "notreal", "marketplace_sku": "X-1"},
    )
    assert resp.status_code == 422
