"""Arbitrage / dynamic-pricing orchestration.

Assembles a :class:`~app.pricing.engine.MarketContext` for each of our live
listings, runs the pure decision engine, records a snapshot + a history row,
and (unless in dry-run) pushes the new price to the marketplace. The engine
NEVER unlists: a listing is only ever repriced or frozen, never deactivated.

Source cost is the cheapest acquisition price found on *other* marketplaces for
the same product (linked via ``sku_mappings``). Competitors are the offers on
the *destination* marketplace. All amounts are converted to the base currency
(EUR) with the FX safety buffer before the engine sees them.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations import build_adapter, resolve_credentials
from app.integrations.base import MarketplaceAdapter, NormalizedListing, to_decimal
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

    # ---- per-listing ------------------------------------------------------
    async def _reprice(
        self,
        listing: Listing,
        dry: bool,
        adapters: dict[str, MarketplaceAdapter],
        summary: ScanSummary,
    ) -> None:
        ctx, competitors, product_id = await self._context_for(listing)

        # Live count of locally-held deliverable codes (G2G stock sync only).
        available = await self._available_stock(listing, product_id)

        if ctx is None:
            # Not enough data for a safe pricing decision, but we may still need
            # to push held-inventory stock up to a G2G offer.
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
            try:
                adapter = self._adapter_for(listing.provider, adapters)
                new_price = decision.new_price if price_changed else listing.price
                new_stock = available if available is not None else listing.stock
                await self._push(adapter, listing, price=new_price, stock=new_stock)
                applied = True
                summary.applied += 1
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
                summary.errors.append(
                    f"{listing.provider}:{listing.marketplace_sku}: push failed: {exc}"
                )

        await self._record_history(
            listing, ctx, decision, product_id, dry, applied, error
        )

    async def _available_stock(
        self, listing: Listing, product_id: int | None
    ) -> int | None:
        """Count of AVAILABLE local codes to mirror as G2G stock, else None.

        Stock-from-inventory is a **G2G-only** behaviour. For any other provider,
        or when the listing maps to no product, returns ``None`` so the caller
        leaves marketplace stock untouched (today's behaviour).
        """
        if listing.provider != "g2g" or product_id is None:
            return None
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
        try:
            adapter = self._adapter_for(listing.provider, adapters)
            await self._push(adapter, listing, price=listing.price, stock=available)
            summary.applied += 1
        except Exception as exc:  # noqa: BLE001
            summary.errors.append(
                f"{listing.provider}:{listing.marketplace_sku}: push failed: {exc}"
            )

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
        source_cost = min(source_prices) if source_prices else dest_base
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
