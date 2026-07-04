"""Auto-import of marketplace offers at the start of each pricing scan.

The operator's recurring pain: creating an offer on G2G and a SKU mapping is not
enough for the bot to sync stock — the offer must first be imported into the
``listings`` table (a "sync listings" step). These tests verify that, when
``PRICING_SYNC_LISTINGS_BEFORE_SCAN`` is on, the scan performs that import itself
so a freshly-created offer is picked up and its stock synced in the same pass —
and that a failing import never blocks repricing of already-known listings.

G2G is exercised in LIVE mode with a respx-mocked transport: the offer-search
endpoint (``POST /v2/offers/search``) feeds the import, the PATCH pushes stock.
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
NEW_OFFER = "G2G-NEW-OFFER"
KNOWN_OFFER = "G2G-KNOWN-OFFER"
STATIC_RATES = {"EUR": Decimal("1"), "USD": Decimal("1.20")}


@pytest.fixture
def currency() -> CurrencyService:
    return CurrencyService(static_rates=STATIC_RATES)


@pytest.fixture
def g2g_autoimport(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Live, credentialed G2G with the pre-scan auto-import turned ON."""
    monkeypatch.setattr(settings, "MARKETPLACE_MODE", "live")
    monkeypatch.setattr(settings, "G2G_API_KEY", "test-key")
    monkeypatch.setattr(settings, "G2G_API_SECRET", "test-secret")
    monkeypatch.setattr(settings, "G2G_API_BASE_URL", G2G_BASE_URL)
    monkeypatch.setattr(settings, "PRICING_SYNC_LISTINGS_BEFORE_SCAN", True)
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


async def _seed_mapping_and_codes(*, sku: str, available: int) -> None:
    """A mapped product with held codes but NO listing row yet.

    This is the operator's "new product" state: offer + mapping + codes exist,
    but the offer has never been imported as a listing, so the scan can't see it
    until the auto-import runs.
    """
    await _wipe()
    async with AsyncSessionLocal() as s:
        product = Product(name="YouTube Premium", internal_sku="YT-1")
        s.add(product)
        await s.flush()
        s.add(SkuMapping(product_id=product.id, marketplace="g2g", marketplace_sku=sku))
        for i in range(available):
            s.add(
                Inventory(
                    product_id=product.id,
                    code=f"YT-{i}",
                    status=InventoryStatus.AVAILABLE,
                )
            )
        await s.commit()


async def _seed_known_listing(*, sku: str, listing_stock: int, available: int) -> None:
    """An already-imported, mapped listing with held codes (the healthy case)."""
    await _wipe()
    async with AsyncSessionLocal() as s:
        product = Product(name="Known Game", internal_sku="KN-1")
        s.add(product)
        await s.flush()
        s.add(SkuMapping(product_id=product.id, marketplace="g2g", marketplace_sku=sku))
        for i in range(available):
            s.add(
                Inventory(
                    product_id=product.id,
                    code=f"KN-{i}",
                    status=InventoryStatus.AVAILABLE,
                )
            )
        s.add(
            Listing(
                provider="g2g",
                marketplace_sku=sku,
                external_listing_id=sku,
                product_id=product.id,
                title="Known Game",
                price=None,
                currency="EUR",
                stock=listing_stock,
                status=ListingStatus.INACTIVE,
            )
        )
        await s.commit()


def _search_returns(router: respx.Router, offers: list[dict]) -> respx.Route:
    return router.post("/v2/offers/search").mock(
        return_value=httpx.Response(200, json={"payload": {"results": offers}})
    )


async def _get_listing(sku: str) -> Listing | None:
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(select(Listing).where(Listing.marketplace_sku == sku))
        ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_scan_imports_new_offer_and_syncs_stock(
    currency: CurrencyService, g2g_autoimport: None
) -> None:
    """A brand-new offer (mapping + codes, no listing) is imported by the scan
    itself and its held-code count is pushed as stock in the same pass."""
    await _seed_mapping_and_codes(sku=NEW_OFFER, available=6)

    with respx.mock(base_url=G2G_BASE_URL, assert_all_called=False) as router:
        _search_returns(
            router,
            [
                {
                    "offer_id": NEW_OFFER,
                    "offer_title": "YouTube Premium",
                    "unit_price": 5.00,
                    "available_qty": 1,  # G2G currently shows 1
                    "currency": "EUR",
                    "status": "live",
                }
            ],
        )
        patch = router.patch(f"/v2/offers/{NEW_OFFER}").mock(
            return_value=httpx.Response(
                200, json={"payload": {"offer_id": NEW_OFFER, "status": "live"}}
            )
        )
        async with AsyncSessionLocal() as s:
            summary = await PricingService(s, currency=currency).scan(
                provider="g2g", dry_run=False
            )

    # The offer was imported as a listing...
    listing = await _get_listing(NEW_OFFER)
    assert listing is not None, "offer should have been auto-imported as a listing"
    # ...and its held-code count (6) was pushed as stock, not the stale 1.
    assert patch.called
    payload = json.loads(patch.calls.last.request.content)
    assert payload["api_qty"] == 6
    assert listing.stock == 6
    assert listing.status is ListingStatus.ACTIVE
    assert summary.errors == []


@pytest.mark.asyncio
async def test_scan_proceeds_when_import_fails(
    currency: CurrencyService, g2g_autoimport: None
) -> None:
    """If the offer-search import errors, the scan must still reprice the
    listings already in the table — the failure is swallowed, not surfaced."""
    await _seed_known_listing(sku=KNOWN_OFFER, listing_stock=0, available=3)

    with respx.mock(base_url=G2G_BASE_URL, assert_all_called=False) as router:
        router.post("/v2/offers/search").mock(
            return_value=httpx.Response(403, json={"error": "blocked"})
        )
        patch = router.patch(f"/v2/offers/{KNOWN_OFFER}").mock(
            return_value=httpx.Response(
                200, json={"payload": {"offer_id": KNOWN_OFFER, "status": "live"}}
            )
        )
        async with AsyncSessionLocal() as s:
            summary = await PricingService(s, currency=currency).scan(
                provider="g2g", dry_run=False
            )

    assert patch.called  # the known listing was still synced
    payload = json.loads(patch.calls.last.request.content)
    assert payload["api_qty"] == 3
    assert summary.applied == 1
    assert summary.errors == []  # the import failure is not a scan error


@pytest.mark.asyncio
async def test_import_disabled_makes_no_search_call(
    currency: CurrencyService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the flag off, the scan does not touch the offer-search endpoint —
    it reprices only what is already in the listings table."""
    monkeypatch.setattr(settings, "MARKETPLACE_MODE", "live")
    monkeypatch.setattr(settings, "G2G_API_KEY", "test-key")
    monkeypatch.setattr(settings, "G2G_API_SECRET", "test-secret")
    monkeypatch.setattr(settings, "G2G_API_BASE_URL", G2G_BASE_URL)
    monkeypatch.setattr(settings, "PRICING_SYNC_LISTINGS_BEFORE_SCAN", False)
    await _seed_known_listing(sku=KNOWN_OFFER, listing_stock=0, available=3)

    with respx.mock(base_url=G2G_BASE_URL, assert_all_called=False) as router:
        search = _search_returns(router, [])
        router.patch(f"/v2/offers/{KNOWN_OFFER}").mock(
            return_value=httpx.Response(200, json={"payload": {}})
        )
        async with AsyncSessionLocal() as s:
            await PricingService(s, currency=currency).scan(
                provider="g2g", dry_run=False
            )

    assert not search.called
