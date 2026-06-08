"""Just-in-time (JIT) sourcing engine.

When we are out of manual stock for a product, this service buys an equivalent
code from the cheapest *other* marketplace, debits the wallet for that provider,
and records the purchased code as a reserved inventory row ready to deliver.

Supplier prioritization = lowest cost converted to the base currency. Funds are
validated (cost + safety buffer) before the purchase so an underfunded wallet
fails fast and the order is retried rather than half-executed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.fulfillment.exceptions import InsufficientFunds, SourcingUnavailable
from app.integrations import build_adapter, resolve_credentials
from app.models.inventory import Inventory, InventoryStatus
from app.repositories.marketplace_price_repository import MarketplacePriceRepository
from app.repositories.sku_mapping_repository import SkuMappingRepository
from app.services.currency_service import CurrencyService
from app.services.wallet_service import WalletService
from app.utils.datetime import utcnow

log = get_logger(__name__)


@dataclass(slots=True)
class _Supplier:
    provider: str
    marketplace_sku: str
    cost: Decimal  # native currency
    currency: str
    base_cost: Decimal  # converted, for comparison


@dataclass(slots=True)
class SourcingResult:
    code: str
    inventory: Inventory
    provider: str
    marketplace_sku: str
    cost: Decimal
    currency: str
    external_purchase_id: str


class SourcingService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        currency: CurrencyService | None = None,
        wallet: WalletService | None = None,
    ) -> None:
        self.session = session
        self.currency = currency or CurrencyService()
        self.wallet = wallet or WalletService(session)
        self.mappings = SkuMappingRepository(session)
        self.prices = MarketplacePriceRepository(session)

    async def source(
        self, product_id: int, dest_provider: str, order_id: int
    ) -> SourcingResult:
        if not settings.JIT_ENABLED:
            raise SourcingUnavailable("JIT sourcing is disabled.")

        supplier = await self._cheapest_supplier(product_id, dest_provider)
        if supplier is None:
            raise SourcingUnavailable(
                f"No source marketplace can supply product {product_id}."
            )

        # Validate funds (cost + safety buffer) before spending anything.
        buffer = Decimal("1") + settings.JIT_SOURCE_BUFFER_PERCENT / Decimal("100")
        required = (supplier.cost * buffer).quantize(Decimal("0.01"))
        balance = await self.wallet.get_balance(supplier.provider, supplier.currency)
        if settings.WALLET_ENFORCE and required > balance:
            raise InsufficientFunds(
                f"{supplier.provider}/{supplier.currency} balance {balance} < "
                f"required {required} for JIT purchase."
            )

        adapter = build_adapter(
            supplier.provider, resolve_credentials(supplier.provider)
        )
        try:
            purchase = await adapter.purchase(
                supplier.marketplace_sku, idempotency_key=f"order-{order_id}"
            )
        finally:
            await adapter.aclose()

        # Debit the wallet for the observed native cost and record the buy.
        await self.wallet.debit(
            supplier.provider,
            supplier.currency,
            supplier.cost,
            order_id=order_id,
            reference=purchase.external_purchase_id,
            notes=f"JIT purchase {supplier.marketplace_sku}",
        )

        inventory = Inventory(
            product_id=product_id,
            code=purchase.code,
            status=InventoryStatus.RESERVED,
            source_cost=supplier.cost,
            currency=supplier.currency,
            reserved_order_id=order_id,
            reserved_at=utcnow(),
            batch_id="jit",
            notes=f"JIT from {supplier.provider}",
            raw={"external_purchase_id": purchase.external_purchase_id},
        )
        self.session.add(inventory)
        await self.session.flush()

        log.info(
            "fulfillment.jit_sourced",
            product_id=product_id,
            supplier=supplier.provider,
            cost=str(supplier.cost),
            currency=supplier.currency,
            order_id=order_id,
        )
        return SourcingResult(
            code=purchase.code,
            inventory=inventory,
            provider=supplier.provider,
            marketplace_sku=supplier.marketplace_sku,
            cost=supplier.cost,
            currency=supplier.currency,
            external_purchase_id=purchase.external_purchase_id,
        )

    async def _cheapest_supplier(
        self, product_id: int, dest_provider: str
    ) -> _Supplier | None:
        candidates: list[_Supplier] = []
        for mapping in await self.mappings.list_for_product(product_id):
            if mapping.marketplace == dest_provider:
                continue
            row = await self.prices.get_by_sku(
                mapping.marketplace, mapping.marketplace_sku
            )
            if row is None or not row.is_available:
                continue
            native = Decimal(row.price)
            currency = row.currency or settings.provider_currency(mapping.marketplace)
            base = await self.currency.to_base(native, currency)
            candidates.append(
                _Supplier(
                    provider=mapping.marketplace,
                    marketplace_sku=mapping.marketplace_sku,
                    cost=native,
                    currency=currency,
                    base_cost=base,
                )
            )
        if not candidates:
            return None
        return min(candidates, key=lambda c: c.base_cost)
