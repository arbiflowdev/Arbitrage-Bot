"""Inventory-driven stock sync to G2G during the pricing scan.

The bot holds deliverable codes locally (the ``inventory`` table). These tests
verify that, for G2G listings, the pricing scan pushes the live count of
AVAILABLE codes up to the mapped offer as ``api_qty`` — so an out-of-stock G2G
offer the bot holds codes for goes Active, and depletion is reflected too.

G2G is exercised in LIVE mode with a respx-mocked transport so the exact wire
payload (``api_qty`` / ``unit_price``) can be asserted.
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
OFFER_ID = "G2G-OFFER-1"
STATIC_RATES = {"EUR": Decimal("1"), "USD": Decimal("1.20")}


@pytest.fixture
def currency() -> CurrencyService:
    return CurrencyService(static_rates=STATIC_RATES)


@pytest.fixture
def g2g_live(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run the scan against a LIVE, credentialed G2G adapter."""
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


async def _seed_inventory_only(*, listing_stock: int, available: int) -> None:
    """A G2G listing mapped to a product with ``available`` codes in stock.

    No marketplace prices and no listing price, so the pricing engine has no
    safe decision to make (ctx is None) — only the stock sync should fire.
    """
    await _wipe()
    async with AsyncSessionLocal() as s:
        product = Product(name="Stock Game", internal_sku="STK-1")
        s.add(product)
        await s.flush()
        pid = product.id
        s.add(SkuMapping(product_id=pid, marketplace="g2g", marketplace_sku=OFFER_ID))
        for i in range(available):
            s.add(
                Inventory(
                    product_id=pid,
                    code=f"CODE-{i}",
                    status=InventoryStatus.AVAILABLE,
                )
            )
        s.add(
            Listing(
                provider="g2g",
                marketplace_sku=OFFER_ID,
                external_listing_id=OFFER_ID,
                product_id=pid,
                title="Stock Game",
                price=None,
                currency="EUR",
                stock=listing_stock,
                status=ListingStatus.INACTIVE,
            )
        )
        await s.commit()


async def _seed_priced(*, listing_stock: int, available: int) -> None:
    """A G2G listing with a real arbitrage opportunity AND held codes.

    Destination (G2G) sells ~20 EUR; sourceable far cheaper on Kinguin, so the
    engine undercuts the competitor. ``available`` codes are held locally.
    """
    await _wipe()
    async with AsyncSessionLocal() as s:
        product = Product(name="Arb Game", internal_sku="ARB-1")
        s.add(product)
        await s.flush()
        pid = product.id
        s.add_all(
            [
                SkuMapping(product_id=pid, marketplace="g2g", marketplace_sku=OFFER_ID),
                SkuMapping(product_id=pid, marketplace="kinguin", marketplace_sku="KIN-1"),
                MarketplacePrice(
                    provider="g2g",
                    marketplace_sku=OFFER_ID,
                    product_id=pid,
                    currency="EUR",
                    price=Decimal("20.00"),  # destination market price
                ),
                MarketplacePrice(
                    provider="kinguin",
                    marketplace_sku="KIN-1",
                    product_id=pid,
                    currency="EUR",
                    price=Decimal("10.00"),  # cheap source
                ),
                Listing(
                    provider="g2g",
                    marketplace_sku=OFFER_ID,
                    external_listing_id=OFFER_ID,
                    product_id=pid,
                    title="Arb Game",
                    price=Decimal("20.00"),
                    currency="EUR",
                    stock=listing_stock,
                    status=ListingStatus.ACTIVE,
                ),
            ]
        )
        for i in range(available):
            s.add(
                Inventory(
                    product_id=pid,
                    code=f"CODE-{i}",
                    status=InventoryStatus.AVAILABLE,
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
            await s.execute(select(Listing).where(Listing.provider == "g2g"))
        ).scalar_one()


@pytest.mark.asyncio
async def test_stock_up_no_price_change_pushes_available_count(
    currency: CurrencyService, g2g_live: None
) -> None:
    """0 stock + 3 held codes, no pricing decision → PATCH api_qty=3."""
    await _seed_inventory_only(listing_stock=0, available=3)

    with respx.mock(base_url=G2G_BASE_URL, assert_all_called=False) as router:
        route = _patch_route(router)
        async with AsyncSessionLocal() as s:
            await PricingService(s, currency=currency).scan(
                provider="g2g", dry_run=False
            )

    assert route.called
    payload = json.loads(route.calls.last.request.content)
    assert payload["api_qty"] == 3
    assert "unit_price" not in payload  # price untouched (was None)

    listing = await _get_listing()
    assert listing.stock == 3
    assert listing.status is ListingStatus.ACTIVE


@pytest.mark.asyncio
async def test_no_change_makes_no_call(
    currency: CurrencyService, g2g_live: None
) -> None:
    """Local count equals listing stock and no price change → no PATCH."""
    await _seed_inventory_only(listing_stock=3, available=3)

    with respx.mock(base_url=G2G_BASE_URL, assert_all_called=False) as router:
        route = _patch_route(router)
        async with AsyncSessionLocal() as s:
            await PricingService(s, currency=currency).scan(
                provider="g2g", dry_run=False
            )

    assert not route.called


@pytest.mark.asyncio
async def test_unmapped_listing_makes_no_call(
    currency: CurrencyService, g2g_live: None
) -> None:
    """A listing with no resolvable product → no stock push, no error."""
    await _wipe()
    async with AsyncSessionLocal() as s:
        s.add(
            Listing(
                provider="g2g",
                marketplace_sku="UNMAPPED-OFFER",
                external_listing_id="UNMAPPED-OFFER",
                product_id=None,
                title="Orphan",
                price=None,
                currency="EUR",
                stock=0,
                status=ListingStatus.INACTIVE,
            )
        )
        await s.commit()

    with respx.mock(base_url=G2G_BASE_URL, assert_all_called=False) as router:
        route = router.patch(url__regex=r".*").mock(
            return_value=httpx.Response(200, json={"payload": {}})
        )
        async with AsyncSessionLocal() as s:
            summary = await PricingService(s, currency=currency).scan(
                provider="g2g", dry_run=False
            )

    assert not route.called
    assert summary.errors == []


@pytest.mark.asyncio
async def test_depletion_pushes_lower_count(
    currency: CurrencyService, g2g_live: None
) -> None:
    """Held codes drop below the offer's stock → PATCH the lower count."""
    await _seed_inventory_only(listing_stock=3, available=2)

    with respx.mock(base_url=G2G_BASE_URL, assert_all_called=False) as router:
        route = _patch_route(router)
        async with AsyncSessionLocal() as s:
            await PricingService(s, currency=currency).scan(
                provider="g2g", dry_run=False
            )

    assert route.called
    payload = json.loads(route.calls.last.request.content)
    assert payload["api_qty"] == 2

    listing = await _get_listing()
    assert listing.stock == 2


@pytest.mark.asyncio
async def test_combined_price_and_stock_single_patch(
    currency: CurrencyService, g2g_live: None
) -> None:
    """A price change and a stock change in one scan → a single PATCH."""
    await _seed_priced(listing_stock=0, available=3)

    with respx.mock(base_url=G2G_BASE_URL, assert_all_called=False) as router:
        route = _patch_route(router)
        async with AsyncSessionLocal() as s:
            await PricingService(s, currency=currency).scan(
                provider="g2g", dry_run=False
            )

    assert route.call_count == 1
    payload = json.loads(route.calls.last.request.content)
    assert payload["api_qty"] == 3
    assert "unit_price" in payload  # repriced in the same push

    listing = await _get_listing()
    assert listing.stock == 3
    assert Decimal(listing.price) < Decimal("20.00")  # undercut applied


@pytest.mark.asyncio
async def test_dry_run_records_history_without_pushing(
    currency: CurrencyService, g2g_live: None
) -> None:
    """Stock differs but dry_run=True → no PATCH; history still recorded."""
    await _seed_priced(listing_stock=0, available=3)

    with respx.mock(base_url=G2G_BASE_URL, assert_all_called=False) as router:
        route = _patch_route(router)
        async with AsyncSessionLocal() as s:
            await PricingService(s, currency=currency).scan(
                provider="g2g", dry_run=True
            )

    assert not route.called

    async with AsyncSessionLocal() as s:
        history = (
            await s.execute(select(RepricingHistory).where(
                RepricingHistory.provider == "g2g"
            ))
        ).scalars().all()
        assert history, "expected a repricing_history row in dry run"

    listing = await _get_listing()
    assert listing.stock == 0  # untouched in dry run
    assert Decimal(listing.price) == Decimal("20.00")
