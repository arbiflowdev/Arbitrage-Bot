"""Arbitrage / dynamic-pricing orchestration.

"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations import (
    SUPPORTED_PROVIDERS,
    build_adapter,
    resolve_credentials,
)
from app.integrations.base import MarketplaceAdapter, NormalizedListing, to_decimal
from app.integrations.exceptions import ProviderAPIError
from app.models.inventory import InventoryStatus
from app.models.listing import Listing, ListingStatus
from app.models.pricing_snapshot import PricingSnapshot
from app.models.repricing_history import RepricingHistory
from app.pricing.engine import MarketContext, PricingPolicy, RepricingDecision, decide
from app.repositories.inventory_repository import InventoryRepository
from app.repositories.listing_repository import ListingRepository
from app.repositories.marketplace_price_repository import MarketplacePriceRepository
from app.repositories.sku_mapping_repository import SkuMappingRepository
from app.schemas.pricing import ScanSummary
from app.services.currency_service import CurrencyService
from app.services.fee_service import FeeService
from app.utils.datetime import utcnow

log = get_logger(__name__)

_MONEY = Decimal("0.01")
_RATE = Decimal("0.0001")
_OFFER_GONE_STATUS = frozenset({404, 410})


def _money(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value).quantize(_MONEY, rounding=ROUND_HALF_UP)


class PricingService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        currency: CurrencyService | None = None,
        fee_service: FeeService | None = None,
    ) -> None:
        self.session = session
        self.currency = currency or CurrencyService()
        self.fees = fee_service or FeeService(session)
        self.listings = ListingRepository(session)
        self.prices = MarketplacePriceRepository(session)
        self.mappings = SkuMappingRepository(session)
        self.inventory = InventoryRepository(session)
        self.policy = PricingPolicy(
            undercut=settings.PRICING_UNDERCUT_AMOUNT,
            min_profit_absolute=settings.PRICING_MIN_PROFIT_ABSOLUTE,
            min_profit_margin=settings.PRICING_MIN_PROFIT_MARGIN_PERCENT / Decimal("100"),
            anomaly_drop=settings.PRICING_ANOMALY_DROP,
            fallback_rank=settings.PRICING_FALLBACK_RANK,
        )

    # ---- public API -------------------------------------------------------
    async def scan(
        self, *, provider: str | None = None, dry_run: bool | None = None
    ) -> ScanSummary:
        """Run one repricing pass over every live listing."""
        dry = settings.PRICING_DRY_RUN if dry_run is None else dry_run
        if settings.PRICING_SYNC_LISTINGS_BEFORE_SCAN:
            await self._import_listings(provider)
        listings = await self.listings.list_by_provider(provider, limit=1000)

        summary = ScanSummary(
            mode=settings.MARKETPLACE_MODE,
            dry_run=dry,
            scanned=0,
            decisions=0,
            applied=0,
        )
        adapters: dict[str, MarketplaceAdapter] = {}
        try:
            for listing in listings:
                if listing.status is ListingStatus.REMOVED:
                    # Remote offer was deleted and the listing was auto-retired;
                    # skip it so it never re-triggers the same 404.
                    continue
                summary.scanned += 1
                try:
                    await self._reprice(listing, dry, adapters, summary)
                except Exception as exc:  # noqa: BLE001 — isolate one listing
                    summary.errors.append(
                        f"{listing.provider}:{listing.marketplace_sku}: {exc}"
                    )
                    log.warning(
                        "pricing.listing_failed",
                        provider=listing.provider,
                        sku=listing.marketplace_sku,
                        error=str(exc),
                    )
            await self.session.commit()
        finally:
            for adapter in adapters.values():
                await adapter.aclose()

        log.info(
            "pricing.scan_complete",
            scanned=summary.scanned,
            decisions=summary.decisions,
            applied=summary.applied,
            dry_run=dry,
        )
        return summary

    async def _import_listings(self, provider: str | None) -> None:
        """Import the marketplace's current offers into the ``listings`` table
        before scanning, so a freshly-created offer is picked up automatically
        (no manual "sync listings" per product).

        Runs for the scanned provider, or every supported provider when scanning
        all. Any failure here (edge block, credentials, provider down) is
        swallowed and logged — importing is best-effort and must never block
        repricing of the listings we already know about.
        """
        # Imported here to avoid a module-level import cycle between the pricing
        # and marketplace services.
        from app.services.marketplace_service import MarketplaceService

        providers = [provider] if provider else list(SUPPORTED_PROVIDERS)
        service = MarketplaceService(self.session)
        for prov in providers:
            try:
                result = await service.sync_listings(prov)
                log.info(
                    "pricing.listings_imported",
                    provider=prov,
                    fetched=result.fetched,
                    upserted=result.upserted,
                )
            except Exception as exc:  # noqa: BLE001 — never block the scan
                log.info(
                    "pricing.listings_import_skipped",
                    provider=prov,
                    error=str(exc),
                )

    # ---- per-listing ------------------------------------------------------
    async def _reprice(
        self,
        listing: Listing,
        dry: bool,
        adapters: dict[str, MarketplaceAdapter],
        summary: ScanSummary,
    ) -> None:
        ctx, competitors, product_id = await self._context_for(listing)

        # Live count of locally-held deliverable codes, mirrored to the
        # marketplace as stock (G2G, Eneba, or any sell-side provider).
        available = await self._available_stock(listing, product_id)

        if ctx is None:
            # Not enough data for a safe pricing decision, but we may still need
            # to push held-inventory stock up to the marketplace listing.
            await self._sync_stock_only(listing, available, dry, adapters, summary)
            return

        decision = decide(ctx)
        summary.decisions += 1
        summary.by_strategy[decision.strategy.value] = (
            summary.by_strategy.get(decision.strategy.value, 0) + 1
        )

        await self._record_snapshot(listing, ctx, competitors, product_id)

        price_changed = decision.changed
        stock_changed = available is not None and available != listing.stock
        applied = False
        error: str | None = None
        if (price_changed or stock_changed) and not dry:
            new_price = decision.new_price if price_changed else listing.price
            new_stock = available if available is not None else listing.stock
            applied, error = await self._attempt_push(
                listing,
                price=new_price,
                stock=new_stock,
                adapters=adapters,
                summary=summary,
            )

        await self._record_history(
            listing, ctx, decision, product_id, dry, applied, error
        )

    async def _available_stock(
        self, listing: Listing, product_id: int | None
    ) -> int | None:
        """Count of AVAILABLE local codes to mirror as marketplace stock, else None.

        Provider-agnostic: we push the held-code count up to whichever
        marketplace the listing sells on (G2G, Eneba, or any future sell-side
        provider). Returns ``None`` when the listing maps to no product, so the
        caller leaves marketplace stock untouched.

        Note: this only ever runs against rows in the ``listings`` table, which
        holds *sell-side* listings. Source-only marketplaces (e.g. Kinguin, which
        the bot buys from and never sells on) surface no listings, so they are
        naturally inert here.

        When ``PRICING_ENFORCE_BACKED_STOCK`` is on, an unmapped listing is not
        left alone but forced to 0: the bot is the source of truth, so an offer
        with no local codes behind it must not keep advertising the marketplace's
        own quantity (which the bot cannot deliver against).
        """
        if product_id is None:
            return 0 if settings.PRICING_ENFORCE_BACKED_STOCK else None
        return await self.inventory.count_status(
            product_id, InventoryStatus.AVAILABLE
        )

    async def _sync_stock_only(
        self,
        listing: Listing,
        available: int | None,
        dry: bool,
        adapters: dict[str, MarketplaceAdapter],
        summary: ScanSummary,
    ) -> None:
        """Push held-inventory stock to G2G when no pricing decision was made.

        Fires only when the marketplace stock actually differs from the local
        AVAILABLE count; preserves the current price (no repricing here).
        """
        if available is None or available == listing.stock or dry:
            return
        await self._attempt_push(
            listing,
            price=listing.price,
            stock=available,
            adapters=adapters,
            summary=summary,
        )

    async def _attempt_push(
        self,
        listing: Listing,
        *,
        price: Decimal | None,
        stock: int,
        adapters: dict[str, MarketplaceAdapter],
        summary: ScanSummary,
    ) -> tuple[bool, str | None]:
        """Push price/stock to the marketplace, isolating per-listing failures.

        Returns ``(applied, error)``. A push to an offer that no longer exists
        (HTTP 404/410) retires the listing locally (see :meth:`_retire_listing`)
        and is deliberately NOT reported as a scan error, so a single stale
        offer can never block stock updates for the rest of the batch. Any other
        failure is surfaced in ``summary.errors`` as before.
        """
        try:
            adapter = self._adapter_for(listing.provider, adapters)
            await self._push(adapter, listing, price=price, stock=stock)
            summary.applied += 1
            return True, None
        except ProviderAPIError as exc:
            if exc.status_code in _OFFER_GONE_STATUS:
                self._retire_listing(listing, exc.status_code)
                summary.retired += 1
                log.info(
                    "pricing.listing_retired",
                    provider=listing.provider,
                    sku=listing.marketplace_sku,
                    status_code=exc.status_code,
                )
                return False, None
            error = str(exc)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
        summary.errors.append(
            f"{listing.provider}:{listing.marketplace_sku}: push failed: {error}"
        )
        return False, error

    def _retire_listing(self, listing: Listing, status_code: int | None) -> None:
        """Retire a listing whose remote offer was deleted (404/410).

        There is nothing to sync to, so we mark it REMOVED and zero its stock.
        The scan skips REMOVED listings, so this stops the recurring error until
        the operator recreates the offer (which re-imports as a fresh listing).
        """
        listing.status = ListingStatus.REMOVED
        listing.stock = 0
        listing.sync_error = (
            f"Remote offer no longer exists (HTTP {status_code}); listing "
            "auto-retired. Recreate the offer on the marketplace to resume syncing."
        )
        listing.last_synced_at = utcnow()

    def _adapter_for(
        self, provider: str, adapters: dict[str, MarketplaceAdapter]
    ) -> MarketplaceAdapter:
        adapter = adapters.get(provider)
        if adapter is None:
            adapter = build_adapter(provider, resolve_credentials(provider))
            adapters[provider] = adapter
        return adapter

    async def _context_for(
        self, listing: Listing
    ) -> tuple[MarketContext | None, list[Decimal], int | None]:
        provider, sku = listing.provider, listing.marketplace_sku

        mapping = await self.mappings.get_by_marketplace_sku(provider, sku)
        product_id = mapping.product_id if mapping else listing.product_id

        # Destination market price (base currency).
        dest_row = await self.prices.get_by_sku(provider, sku)
        dest_base: Decimal | None = None
        if dest_row is not None:
            dest_base = await self.currency.to_base(
                Decimal(dest_row.price),
                dest_row.currency or settings.provider_currency(provider),
            )
        elif listing.price is not None:
            dest_base = Decimal(listing.price)

        # Source cost: cheapest acquisition on OTHER marketplaces.
        source_prices: list[Decimal] = []
        if product_id is not None:
            for m in await self.mappings.list_for_product(product_id):
                if m.marketplace == provider:
                    continue
                row = await self.prices.get_by_sku(m.marketplace, m.marketplace_sku)
                if row is not None and row.is_available:
                    source_prices.append(
                        await self.currency.to_base(
                            Decimal(row.price),
                            row.currency or settings.provider_currency(m.marketplace),
                        )
                    )
        # Source cost is what we PAY to acquire on another marketplace — never
        # our own selling price. Falling back to ``dest_base`` (this listing's
        # own destination price) is catastrophic: ``minimum_safe_price`` returns
        # ``source_cost / (k - margin)`` — strictly above the current price — so
        # the pushed price is stored back into ``listing.price`` and becomes the
        # next scan's "cost", ratcheting the price up geometrically every scan.
        # With no genuine source cost we have no basis to judge profitability, so
        # we return no context: the listing is frozen (price untouched) and only
        # its stock is mirrored. Repricing resumes once a real source mapping/
        # price exists for the product.
        source_cost = min(source_prices) if source_prices else None
        if source_cost is None:
            return None, [], product_id

        competitors = await self._competitor_book(provider, sku, dest_row, dest_base)
        fees = await self.fees.params_for(provider)
        current = Decimal(listing.price) if listing.price is not None else None
        ctx = MarketContext(
            source_cost=source_cost,
            competitors=competitors,
            fees=fees,
            current_price=current,
            policy=self.policy,
        )
        return ctx, sorted(competitors), product_id

    async def _competitor_book(
        self,
        provider: str,
        sku: str,
        dest_row: object | None,
        dest_base: Decimal | None,
    ) -> list[Decimal]:
        """Competitor offers on the destination marketplace (base currency).

        The live marketplaces expose a multi-seller offer list per product.
        Adapters drop that list into ``marketplace_prices.raw['offers']`` during
        price sync (each entry a number or an object with a ``price``/``amount``
        field, in the row's currency); the engine then prices against the real
        book. When no offer list is present we fall back to a deterministic
        synthesised book in mock mode (so demos exercise Top-3 / anomaly), or to
        the single prevailing price in live mode.
        """
        raw = getattr(dest_row, "raw", None)
        currency = (
            getattr(dest_row, "currency", None) or settings.provider_currency(provider)
        )
        if isinstance(raw, dict) and isinstance(raw.get("offers"), list):
            offers: list[Decimal] = []
            for entry in raw["offers"]:
                value = entry
                if isinstance(entry, dict):
                    value = entry.get("price", entry.get("amount"))
                amount = to_decimal(value)
                if amount is not None and amount > 0:
                    offers.append(await self.currency.to_base(amount, currency))
            if offers:
                return offers

        if dest_base is None:
            return []
        if settings.MARKETPLACE_MODE == "mock":
            return [
                dest_base,
                dest_base + Decimal("0.20"),
                dest_base + Decimal("0.40"),
            ]
        return [dest_base]

    # ---- persistence ------------------------------------------------------
    async def _record_snapshot(
        self,
        listing: Listing,
        ctx: MarketContext,
        competitors: list[Decimal],
        product_id: int | None,
    ) -> None:
        ordered = competitors  # already sorted ascending
        snapshot = PricingSnapshot(
            provider=listing.provider,
            marketplace_sku=listing.marketplace_sku,
            product_id=product_id,
            base_currency=settings.BASE_CURRENCY,
            lowest_price=_money(ordered[0]) if ordered else None,
            second_price=_money(ordered[1]) if len(ordered) > 1 else None,
            third_price=_money(ordered[2]) if len(ordered) > 2 else None,
            source_cost=_money(ctx.source_cost),
            competitor_count=len(ordered),
            competitors=[float(c) for c in ordered],
        )
        self.session.add(snapshot)

    async def _record_history(
        self,
        listing: Listing,
        ctx: MarketContext,
        decision: RepricingDecision,
        product_id: int | None,
        dry: bool,
        applied: bool,
        error: str | None,
    ) -> None:
        b = decision.breakdown
        history = RepricingHistory(
            provider=listing.provider,
            marketplace_sku=listing.marketplace_sku,
            product_id=product_id,
            listing_id=listing.id,
            strategy=decision.strategy.value,
            currency=settings.BASE_CURRENCY,
            old_price=_money(Decimal(listing.price)) if listing.price is not None else None,
            new_price=_money(decision.new_price),
            net_profit=_money(b.net_profit),
            margin=Decimal(b.margin).quantize(_RATE, rounding=ROUND_HALF_UP),
            source_cost=_money(ctx.source_cost),
            sales_fee=_money(b.sales_fee),
            withdrawal_fee=_money(b.withdrawal_fee),
            competitor_reference=_money(decision.competitor_reference),
            anomaly_detected=decision.anomaly_detected,
            changed=decision.changed,
            applied=applied,
            dry_run=dry,
            error=error,
            notes=(decision.notes or None) and decision.notes[:512],
        )
        self.session.add(history)

    async def _push(
        self,
        adapter: MarketplaceAdapter,
        listing: Listing,
        *,
        price: Decimal | None,
        stock: int,
    ) -> None:
        """Push price and/or stock; keep the listing live (never unlist)."""
        await adapter.push_listing(
            NormalizedListing(
                marketplace_sku=listing.marketplace_sku,
                external_listing_id=listing.external_listing_id,
                title=listing.title,
                price=price,
                currency=listing.currency or settings.BASE_CURRENCY,
                stock=stock,
                status="active",
            )
        )
        if price is not None:
            listing.price = price
        listing.stock = stock
        listing.status = ListingStatus.ACTIVE  # never deactivate
        listing.last_synced_at = utcnow()
        listing.sync_error = None
