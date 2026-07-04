"""Regression: the repricer must never use our own selling price as the source
cost, because doing so makes the price compound geometrically every scan.

The bug (production, 2026-07-04): a G2G offer with held codes and a SKU mapping
but NO genuine source cost (no other-marketplace mapping/price) had its
``source_cost`` fall back to its own destination price. ``minimum_safe_price``
then returns ``source_cost / (k - margin)`` — strictly *above* the current price
— which was pushed and stored back into ``listing.price`` and became the next
scan's source cost. Over a few hours this ratcheted YouTube to 937,526,104.85.

Correct behaviour: with no real cost basis the engine cannot judge
profitability, so it must FREEZE (leave the operator's price untouched) and only
mirror stock. These tests pin that: a no-source listing is never repriced, and
repeated scans never inflate the price.

G2G runs LIVE with a respx-mocked transport so we can assert the exact wire
payload (and that no runaway ``unit_price`` is ever sent).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from decimal import Decimal

import httpx
import pytest
import respx
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.inventory import Inventory, InventoryStatus
from app.models.listing import Listing, ListingStatus
from app.models.marketplace_price import MarketplacePrice
from app.models.pricing_snapshot import PricingSnapshot
from app.models.product import Product
from app.models.repricing_history import RepricingHistory
from app.models.sku_mapping import SkuMapping
from app.services.currency_service import CurrencyService
from app.services.pricing_service import PricingService

G2G_BASE_URL = "https://open-api.g2g.com"
OFFER_ID = "G2G-NO-SOURCE"
LIST_PRICE = Decimal("5.00")
STATIC_RATES = {"EUR": Decimal("1"), "USD": Decimal("1.20")}


@pytest.fixture
def currency() -> CurrencyService:
    return CurrencyService(static_rates=STATIC_RATES)


@pytest.fixture
def g2g_live(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "MARKETPLACE_MODE", "live")
    monkeypatch.setattr(settings, "G2G_API_KEY", "test-key")
    monkeypatch.setattr(settings, "G2G_API_SECRET", "test-secret")
    monkeypatch.setattr(settings, "G2G_API_BASE_URL", G2G_BASE_URL)
    yield


async def _wipe() -> None:
    async with AsyncSessionLocal() as s:
        for model in (
            RepricingHistory,
            PricingSnapshot,
            Listing,
            MarketplacePrice,
            SkuMapping,
            Inventory,
            Product,
        ):
            await s.execute(delete(model))
        await s.commit()


async def _seed_no_source(*, listing_stock: int, available: int) -> None:
    """A priced, mapped G2G listing with held codes but NO cost basis.

    Only a g2g mapping exists — there is no other-marketplace source mapping and
    no marketplace_prices row — so the repricer has no legitimate source cost.
    This is the exact shape of the offers that exploded in production.
    """
    await _wipe()
    async with AsyncSessionLocal() as s:
        product = Product(name="No-Source Game", internal_sku="NS-1")
        s.add(product)
        await s.flush()
        pid = product.id
        s.add(SkuMapping(product_id=pid, marketplace="g2g", marketplace_sku=OFFER_ID))
        for i in range(available):
            s.add(
                Inventory(
                    product_id=pid,
                    code=f"NS-{i}",
                    status=InventoryStatus.AVAILABLE,
                )
            )
        s.add(
            Listing(
                provider="g2g",
                marketplace_sku=OFFER_ID,
                external_listing_id=OFFER_ID,
                product_id=pid,
                title="No-Source Game",
                price=LIST_PRICE,
                currency="USD",
                stock=listing_stock,
                status=ListingStatus.ACTIVE,
            )
        )
        await s.commit()


def _patch_route(router: respx.Router) -> respx.Route:
    return router.patch(f"/v2/offers/{OFFER_ID}").mock(
        return_value=httpx.Response(
            200, json={"payload": {"offer_id": OFFER_ID, "status": "live"}}
        )
    )


async def _get_listing() -> Listing:
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(select(Listing).where(Listing.marketplace_sku == OFFER_ID))
        ).scalar_one()


@pytest.mark.asyncio
async def test_no_source_cost_does_not_reprice(
    currency: CurrencyService, g2g_live: None
) -> None:
    """No cost basis + stock already correct → the scan must not push at all,
    and must leave the operator's price exactly as set (no self-referential
    minimum-safe-price ratchet)."""
    await _seed_no_source(listing_stock=6, available=6)

    with respx.mock(base_url=G2G_BASE_URL, assert_all_called=False) as router:
        route = _patch_route(router)
        async with AsyncSessionLocal() as s:
            summary = await PricingService(s, currency=currency).scan(
                provider="g2g", dry_run=False
            )

    assert not route.called, "a listing with no source cost must not be repriced"
    assert summary.errors == []
    listing = await _get_listing()
    assert Decimal(listing.price) == LIST_PRICE


@pytest.mark.asyncio
async def test_repeated_scans_never_inflate_price(
    currency: CurrencyService, g2g_live: None
) -> None:
    """Run the scan repeatedly: the price must stay put. If any push happens, its
    unit_price must equal the frozen price — never a compounding multiple."""
    await _seed_no_source(listing_stock=6, available=6)

    for _ in range(3):
        with respx.mock(base_url=G2G_BASE_URL, assert_all_called=False) as router:
            route = _patch_route(router)
            async with AsyncSessionLocal() as s:
                await PricingService(s, currency=currency).scan(
                    provider="g2g", dry_run=False
                )
            if route.called:
                payload = json.loads(route.calls.last.request.content)
                sent = payload.get("unit_price")
                assert sent is None or Decimal(sent) == LIST_PRICE, (
                    f"price inflated to {sent}; expected it frozen at {LIST_PRICE}"
                )

    listing = await _get_listing()
    assert Decimal(listing.price) == LIST_PRICE
