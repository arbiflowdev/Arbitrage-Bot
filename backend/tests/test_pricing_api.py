"""Tests for the pricing-engine API (admin only, mock mode)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.listing import Listing, ListingStatus
from app.models.marketplace_price import MarketplacePrice
from app.models.pricing_snapshot import PricingSnapshot
from app.models.product import Product
from app.models.repricing_history import RepricingHistory
from app.models.sku_mapping import SkuMapping


async def _seed_eur_listing() -> None:
    """EUR-only data so the scan needs no FX lookup (no network in tests)."""
    async with AsyncSessionLocal() as s:
        for model in (
            RepricingHistory,
            PricingSnapshot,
            Listing,
            MarketplacePrice,
            SkuMapping,
            Product,
        ):
            await s.execute(delete(model))
        await s.commit()

        product = Product(name="API Game", internal_sku="API-1")
        s.add(product)
        await s.flush()
        pid = product.id
        s.add_all(
            [
                SkuMapping(product_id=pid, marketplace="kinguin", marketplace_sku="K-API-1"),
                SkuMapping(product_id=pid, marketplace="eneba", marketplace_sku="E-API-1"),
                MarketplacePrice(
                    provider="kinguin",
                    marketplace_sku="K-API-1",
                    product_id=pid,
                    currency="EUR",
                    price=Decimal("30.00"),
                ),
                MarketplacePrice(
                    provider="eneba",
                    marketplace_sku="E-API-1",
                    product_id=pid,
                    currency="EUR",
                    price=Decimal("12.00"),  # cheap supply
                ),
                Listing(
                    provider="kinguin",
                    marketplace_sku="K-API-1",
                    product_id=pid,
                    title="API Game",
                    price=Decimal("30.00"),
                    currency="EUR",
                    stock=10,
                    status=ListingStatus.ACTIVE,
                ),
            ]
        )
        await s.commit()


@pytest.mark.asyncio
async def test_pricing_status_requires_admin(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/pricing/status")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_pricing_status_reports_config(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    resp = await client.get("/api/v1/pricing/status", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "mock"
    assert body["scan_interval_seconds"] == 60
    assert body["base_currency"] == "EUR"
    assert Decimal(str(body["min_profit_absolute"])) == Decimal("0.30")


@pytest.mark.asyncio
async def test_preview_scan_records_history_without_applying(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    await _seed_eur_listing()
    resp = await client.post(
        "/api/v1/pricing/preview?provider=kinguin", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    summary = resp.json()
    assert summary["dry_run"] is True
    assert summary["decisions"] >= 1
    assert summary["applied"] == 0

    history = await client.get(
        "/api/v1/repricing-history?provider=kinguin", headers=admin_headers
    )
    assert history.status_code == 200
    rows = history.json()
    assert rows and rows[0]["provider"] == "kinguin"
    assert rows[0]["dry_run"] is True


@pytest.mark.asyncio
async def test_kill_switch_toggles(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    off = await client.post(
        "/api/v1/pricing/kill-switch",
        headers=admin_headers,
        json={"enabled": False},
    )
    assert off.status_code == 200, off.text
    assert off.json()["enabled"] is False

    on = await client.post(
        "/api/v1/pricing/kill-switch",
        headers=admin_headers,
        json={"enabled": True},
    )
    assert on.status_code == 200
    assert on.json()["enabled"] is True
