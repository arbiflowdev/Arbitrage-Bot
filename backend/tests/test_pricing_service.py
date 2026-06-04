"""Integration tests for the pricing service scan loop (mock mode, SQLite)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.listing import Listing, ListingStatus
from app.models.marketplace_price import MarketplacePrice
from app.models.pricing_snapshot import PricingSnapshot
from app.models.product import Product
from app.models.repricing_history import RepricingHistory
from app.models.sku_mapping import SkuMapping
from app.repositories.repricing_history_repository import (
    RepricingHistoryRepository,
)
from app.services.currency_service import CurrencyService
from app.services.pricing_service import PricingService

STATIC_RATES = {"EUR": Decimal("1"), "USD": Decimal("1.20")}


@pytest.fixture
def currency() -> CurrencyService:
    return CurrencyService(static_rates=STATIC_RATES)


async def _reset_and_seed() -> int:
    """Wipe pricing-related tables and seed one arbitrage product.

    Product sells on Kinguin at ~20 EUR but is sourceable far cheaper, so the
    engine should undercut the cheapest destination competitor profitably.
    """
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

        product = Product(name="Arb Game", internal_sku="ARB-1")
        s.add(product)
        await s.flush()
        pid = product.id
        s.add_all(
            [
                SkuMapping(product_id=pid, marketplace="kinguin", marketplace_sku="KIN-1"),
                SkuMapping(product_id=pid, marketplace="g2g", marketplace_sku="G2G-1"),
                SkuMapping(product_id=pid, marketplace="eneba", marketplace_sku="ENB-1"),
                MarketplacePrice(
                    provider="kinguin",
                    marketplace_sku="KIN-1",
                    product_id=pid,
                    currency="EUR",
                    price=Decimal("20.00"),  # destination market price
                ),
                MarketplacePrice(
                    provider="g2g",
                    marketplace_sku="G2G-1",
                    product_id=pid,
                    currency="USD",
                    price=Decimal("12.00"),  # -> 10.00 EUR + 1% buffer = 10.10
                ),
                MarketplacePrice(
                    provider="eneba",
                    marketplace_sku="ENB-1",
                    product_id=pid,
                    currency="EUR",
                    price=Decimal("11.00"),
                ),
                Listing(
                    provider="kinguin",
                    marketplace_sku="KIN-1",
                    product_id=pid,
                    title="Arb Game",
                    price=Decimal("20.00"),
                    currency="EUR",
                    stock=50,
                    status=ListingStatus.ACTIVE,
                ),
            ]
        )
        await s.commit()
        return pid


@pytest.mark.asyncio
async def test_scan_dry_run_records_decision_without_pushing(
    currency: CurrencyService,
) -> None:
    await _reset_and_seed()
    async with AsyncSessionLocal() as s:
        summary = await PricingService(s, currency=currency).scan(
            provider="kinguin", dry_run=True
        )

    assert summary.scanned >= 1
    assert summary.decisions >= 1
    assert summary.applied == 0  # dry run never pushes

    async with AsyncSessionLocal() as s:
        history = await RepricingHistoryRepository(s).list_recent("kinguin")
        assert history, "expected a repricing_history row"
        row = history[0]
        assert row.strategy == "undercut"
        assert Decimal(row.new_price) == Decimal("19.99")  # undercut 20.00 by 0.01
        assert Decimal(row.source_cost) == Decimal("10.10")  # 12 USD -> 10 + 1%
        assert row.dry_run is True
        assert row.applied is False

        listing = (
            await s.execute(select(Listing).where(Listing.provider == "kinguin"))
        ).scalar_one()
        assert Decimal(listing.price) == Decimal("20.00")  # unchanged in dry run
        assert listing.status is ListingStatus.ACTIVE  # never unlisted


@pytest.mark.asyncio
async def test_real_competitor_offer_book_is_used_over_single_price(
    currency: CurrencyService,
) -> None:
    """When a marketplace exposes a multi-seller offer list (stored in
    ``marketplace_prices.raw['offers']``), the engine prices against that book
    rather than the single prevailing price or the mock synthesis."""
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

        product = Product(name="Book Game", internal_sku="BOOK-1")
        s.add(product)
        await s.flush()
        pid = product.id
        s.add_all(
            [
                SkuMapping(product_id=pid, marketplace="kinguin", marketplace_sku="KB-1"),
                SkuMapping(product_id=pid, marketplace="eneba", marketplace_sku="EB-1"),
                MarketplacePrice(
                    provider="kinguin",
                    marketplace_sku="KB-1",
                    product_id=pid,
                    currency="EUR",
                    price=Decimal("30.00"),  # single prevailing price...
                    raw={"offers": [15.00, 15.30, 15.60]},  # ...but a real book exists
                ),
                MarketplacePrice(
                    provider="eneba",
                    marketplace_sku="EB-1",
                    product_id=pid,
                    currency="EUR",
                    price=Decimal("5.00"),  # cheap supply
                ),
                Listing(
                    provider="kinguin",
                    marketplace_sku="KB-1",
                    product_id=pid,
                    title="Book Game",
                    price=Decimal("30.00"),
                    currency="EUR",
                    stock=10,
                    status=ListingStatus.ACTIVE,
                ),
            ]
        )
        await s.commit()

    async with AsyncSessionLocal() as s:
        await PricingService(s, currency=currency).scan(
            provider="kinguin", dry_run=True
        )

    async with AsyncSessionLocal() as s:
        row = (await RepricingHistoryRepository(s).list_recent("kinguin"))[0]
        # Undercuts the cheapest *offer* (15.00), not the 30.00 single price.
        assert row.strategy == "undercut"
        assert Decimal(row.new_price) == Decimal("14.99")
        snapshot = (
            await s.execute(select(PricingSnapshot).where(
                PricingSnapshot.provider == "kinguin"
            ))
        ).scalars().first()
        assert Decimal(snapshot.lowest_price) == Decimal("15.00")
        assert snapshot.competitor_count == 3


@pytest.mark.asyncio
async def test_scan_live_applies_price_and_keeps_listing_active(
    currency: CurrencyService,
) -> None:
    await _reset_and_seed()
    async with AsyncSessionLocal() as s:
        summary = await PricingService(s, currency=currency).scan(
            provider="kinguin", dry_run=False
        )

    assert summary.applied >= 1

    async with AsyncSessionLocal() as s:
        listing = (
            await s.execute(select(Listing).where(Listing.provider == "kinguin"))
        ).scalar_one()
        assert Decimal(listing.price) == Decimal("19.99")
        assert listing.status is ListingStatus.ACTIVE  # never unlisted
