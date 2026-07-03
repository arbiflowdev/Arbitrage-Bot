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
DEAD_OFFER_ID = "G2G-DELETED-OFFER"
STATIC_RATES = {"EUR": Decimal("1"), "USD": Decimal("1.20")}

ENEBA_BASE_URL = "https://api.eneba.com"
ENEBA_GRAPHQL_URL = f"{ENEBA_BASE_URL}/graphql/"
ENEBA_OAUTH_URL = "https://user.eneba.com/oauth/token"
ENEBA_PRODUCT_SKU = "ENB-PRODUCT-1"
ENEBA_AUCTION_ID = "ENB-AUCTION-1"


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


@pytest.fixture
def eneba_live(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run the scan against a LIVE, credentialed Eneba adapter."""
    monkeypatch.setattr(settings, "MARKETPLACE_MODE", "live")
    monkeypatch.setattr(settings, "ENEBA_CLIENT_ID", "test-auth-id")
    monkeypatch.setattr(settings, "ENEBA_AUTH_ID", None)
    monkeypatch.setattr(settings, "ENEBA_API_SECRET", "test-secret")
    monkeypatch.setattr(settings, "ENEBA_API_BASE_URL", ENEBA_BASE_URL)
    monkeypatch.setattr(settings, "ENEBA_OAUTH_TOKEN_URL", ENEBA_OAUTH_URL)
    monkeypatch.setattr(settings, "ENEBA_OAUTH_CLIENT_ID", "fixed-client")
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


async def _seed_eneba_inventory_only(*, listing_stock: int, available: int) -> None:
    """An Eneba listing (existing auction) mapped to a product with held codes.

    No marketplace prices and no listing price, so the only thing the scan can
    do is mirror the held-code count up to the Eneba auction as stock.
    """
    await _wipe()
    async with AsyncSessionLocal() as s:
        product = Product(name="Eneba Game", internal_sku="ENB-1")
        s.add(product)
        await s.flush()
        pid = product.id
        s.add(
            SkuMapping(
                product_id=pid, marketplace="eneba", marketplace_sku=ENEBA_PRODUCT_SKU
            )
        )
        for i in range(available):
            s.add(
                Inventory(
                    product_id=pid,
                    code=f"ECODE-{i}",
                    status=InventoryStatus.AVAILABLE,
                )
            )
        s.add(
            Listing(
                provider="eneba",
                marketplace_sku=ENEBA_PRODUCT_SKU,
                external_listing_id=ENEBA_AUCTION_ID,
                product_id=pid,
                title="Eneba Game",
                price=None,
                currency="EUR",
                stock=listing_stock,
                status=ListingStatus.INACTIVE,
            )
        )
        await s.commit()


async def _seed_two_listings_one_dead(*, available: int) -> None:
    """Two mapped G2G listings, each with held codes: one live, one whose remote
    offer has been deleted (its PATCH will 404). Mirrors the operator's real
    dashboard: a stale deleted offer sitting alongside a freshly-set-up one.
    """
    await _wipe()
    async with AsyncSessionLocal() as s:
        good = Product(name="Good Game", internal_sku="GOOD-1")
        dead = Product(name="Dead Game", internal_sku="DEAD-1")
        s.add_all([good, dead])
        await s.flush()
        s.add_all(
            [
                SkuMapping(
                    product_id=good.id, marketplace="g2g", marketplace_sku=OFFER_ID
                ),
                SkuMapping(
                    product_id=dead.id,
                    marketplace="g2g",
                    marketplace_sku=DEAD_OFFER_ID,
                ),
            ]
        )
        for i in range(available):
            s.add(
                Inventory(
                    product_id=good.id,
                    code=f"GOOD-{i}",
                    status=InventoryStatus.AVAILABLE,
                )
            )
            s.add(
                Inventory(
                    product_id=dead.id,
                    code=f"DEAD-{i}",
                    status=InventoryStatus.AVAILABLE,
                )
            )
        s.add_all(
            [
                Listing(
                    provider="g2g",
                    marketplace_sku=OFFER_ID,
                    external_listing_id=OFFER_ID,
                    product_id=good.id,
                    title="Good Game",
                    price=None,
                    currency="EUR",
                    stock=0,
                    status=ListingStatus.INACTIVE,
                ),
                Listing(
                    provider="g2g",
                    marketplace_sku=DEAD_OFFER_ID,
                    external_listing_id=DEAD_OFFER_ID,
                    product_id=dead.id,
                    title="Dead Game",
                    price=None,
                    currency="EUR",
                    stock=0,
                    status=ListingStatus.INACTIVE,
                ),
            ]
        )
        await s.commit()


def _patch_route(router: respx.Router) -> respx.Route:
    return router.patch(f"/v2/offers/{OFFER_ID}").mock(
        return_value=httpx.Response(
            200, json={"payload": {"offer_id": OFFER_ID, "status": "live"}}
        )
    )


async def _get_listing(provider: str = "g2g") -> Listing:
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(select(Listing).where(Listing.provider == provider))
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


@pytest.mark.asyncio
async def test_eneba_stock_up_pushes_available_count(
    currency: CurrencyService, eneba_live: None
) -> None:
    """Inventory→stock sync is provider-agnostic: an Eneba auction gets the
    held-code count pushed as stock, exactly like G2G."""
    await _seed_eneba_inventory_only(listing_stock=0, available=3)

    with respx.mock(assert_all_called=False) as router:
        router.post(ENEBA_OAUTH_URL).mock(
            return_value=httpx.Response(
                200, json={"access_token": "tok", "expires_in": 3600}
            )
        )
        gql = router.post(ENEBA_GRAPHQL_URL).mock(
            return_value=httpx.Response(
                200, json={"data": {"S_updateAuction": {"id": "action-1"}}}
            )
        )
        async with AsyncSessionLocal() as s:
            await PricingService(s, currency=currency).scan(
                provider="eneba", dry_run=False
            )

    assert gql.called
    body = json.loads(gql.calls.last.request.content)
    assert body["variables"]["input"]["stock"] == 3

    listing = await _get_listing("eneba")
    assert listing.stock == 3
    assert listing.status is ListingStatus.ACTIVE


@pytest.mark.asyncio
async def test_deleted_offer_404_auto_retires(
    currency: CurrencyService, g2g_live: None
) -> None:
    """A push to a deleted remote offer (404) retires the listing locally and is
    NOT reported as a scan error — it must never block the rest of the batch."""
    await _seed_inventory_only(listing_stock=0, available=3)

    with respx.mock(base_url=G2G_BASE_URL, assert_all_called=False) as router:
        route = router.patch(f"/v2/offers/{OFFER_ID}").mock(
            return_value=httpx.Response(404, json={"error": "offer not found"})
        )
        async with AsyncSessionLocal() as s:
            summary = await PricingService(s, currency=currency).scan(
                provider="g2g", dry_run=False
            )

    assert route.called
    assert summary.errors == []  # 404 is not a hard error
    assert summary.applied == 0
    assert summary.retired == 1

    listing = await _get_listing()
    assert listing.status is ListingStatus.REMOVED
    assert listing.stock == 0
    assert listing.sync_error and "404" in listing.sync_error


@pytest.mark.asyncio
async def test_removed_listing_skipped_on_next_scan(
    currency: CurrencyService, g2g_live: None
) -> None:
    """Once retired (404), a listing is skipped entirely on subsequent scans —
    no repeat push, no repeat error."""
    await _seed_inventory_only(listing_stock=0, available=3)

    with respx.mock(base_url=G2G_BASE_URL, assert_all_called=False) as router:
        router.patch(f"/v2/offers/{OFFER_ID}").mock(
            return_value=httpx.Response(404, json={})
        )
        async with AsyncSessionLocal() as s:
            await PricingService(s, currency=currency).scan(
                provider="g2g", dry_run=False
            )

    with respx.mock(base_url=G2G_BASE_URL, assert_all_called=False) as router:
        route = router.patch(url__regex=r".*").mock(
            return_value=httpx.Response(200, json={"payload": {}})
        )
        async with AsyncSessionLocal() as s:
            summary = await PricingService(s, currency=currency).scan(
                provider="g2g", dry_run=False
            )

    assert not route.called
    assert summary.scanned == 0  # the only listing is retired and skipped


@pytest.mark.asyncio
async def test_non_gone_push_error_still_reported(
    currency: CurrencyService, g2g_live: None
) -> None:
    """A genuine push error (e.g. 400) is still surfaced and does NOT retire the
    listing — we only auto-retire on 'offer gone' (404/410)."""
    await _seed_inventory_only(listing_stock=0, available=3)

    with respx.mock(base_url=G2G_BASE_URL, assert_all_called=False) as router:
        router.patch(f"/v2/offers/{OFFER_ID}").mock(
            return_value=httpx.Response(400, json={"error": "bad request"})
        )
        async with AsyncSessionLocal() as s:
            summary = await PricingService(s, currency=currency).scan(
                provider="g2g", dry_run=False
            )

    assert summary.errors  # real errors are not swallowed
    assert summary.retired == 0

    listing = await _get_listing()
    assert listing.status is not ListingStatus.REMOVED


@pytest.mark.asyncio
async def test_deleted_offer_does_not_block_healthy_listing(
    currency: CurrencyService, g2g_live: None
) -> None:
    """The operator's exact scenario: one stale deleted offer (404) sitting next
    to a freshly-configured live listing. The healthy one must still sync."""
    await _seed_two_listings_one_dead(available=6)

    with respx.mock(base_url=G2G_BASE_URL, assert_all_called=False) as router:
        good = router.patch(f"/v2/offers/{OFFER_ID}").mock(
            return_value=httpx.Response(200, json={"payload": {"offer_id": OFFER_ID}})
        )
        dead = router.patch(f"/v2/offers/{DEAD_OFFER_ID}").mock(
            return_value=httpx.Response(404, json={"error": "offer not found"})
        )
        async with AsyncSessionLocal() as s:
            summary = await PricingService(s, currency=currency).scan(
                provider="g2g", dry_run=False
            )

    assert good.called
    assert dead.called
    assert summary.applied == 1  # the healthy listing still pushed
    assert summary.errors == []  # the dead one was retired, not errored

    async with AsyncSessionLocal() as s:
        good_listing = (
            await s.execute(select(Listing).where(Listing.marketplace_sku == OFFER_ID))
        ).scalar_one()
        dead_listing = (
            await s.execute(
                select(Listing).where(Listing.marketplace_sku == DEAD_OFFER_ID)
            )
        ).scalar_one()

    assert good_listing.stock == 6
    assert good_listing.status is ListingStatus.ACTIVE
    assert dead_listing.status is ListingStatus.REMOVED
    assert dead_listing.stock == 0
