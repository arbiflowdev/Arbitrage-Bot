"""Integration tests for the JIT SourcingService (SQLite, mock mode)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.fulfillment.exceptions import InsufficientFunds, SourcingUnavailable
from app.models.inventory import Inventory, InventoryStatus
from app.models.marketplace_price import MarketplacePrice
from app.models.product import Product
from app.models.sku_mapping import SkuMapping
from app.models.transaction import Transaction, TransactionType
from app.models.wallet_balance import WalletBalance
from app.services.currency_service import CurrencyService
from app.services.sourcing_service import SourcingService
from app.services.wallet_service import WalletService

STATIC_RATES = {"EUR": Decimal("1"), "USD": Decimal("1.20")}


def _currency() -> CurrencyService:
    return CurrencyService(static_rates=STATIC_RATES)


async def _seed() -> int:
    """Dest = kinguin; sources = g2g (12 USD ~= 10.10 base) and eneba (11 EUR).

    g2g is the cheapest source in base currency, so JIT should pick it.
    """
    async with AsyncSessionLocal() as s:
        for model in (
            Transaction,
            WalletBalance,
            Inventory,
            MarketplacePrice,
            SkuMapping,
            Product,
        ):
            await s.execute(delete(model))
        await s.commit()
        product = Product(name="JIT Game", internal_sku="JIT-1")
        s.add(product)
        await s.flush()
        pid = product.id
        s.add_all(
            [
                SkuMapping(product_id=pid, marketplace="kinguin", marketplace_sku="KIN-1"),
                SkuMapping(product_id=pid, marketplace="g2g", marketplace_sku="G2G-1"),
                SkuMapping(product_id=pid, marketplace="eneba", marketplace_sku="ENB-1"),
                MarketplacePrice(
                    provider="g2g",
                    marketplace_sku="G2G-1",
                    product_id=pid,
                    currency="USD",
                    price=Decimal("12.00"),
                ),
                MarketplacePrice(
                    provider="eneba",
                    marketplace_sku="ENB-1",
                    product_id=pid,
                    currency="EUR",
                    price=Decimal("11.00"),
                ),
            ]
        )
        await s.commit()
        return pid


@pytest.mark.asyncio
async def test_source_picks_cheapest_supplier_and_debits_wallet() -> None:
    pid = await _seed()
    async with AsyncSessionLocal() as s:
        await WalletService(s).top_up("g2g", "USD", Decimal("100.00"))
        await s.commit()

    async with AsyncSessionLocal() as s:
        result = await SourcingService(s, currency=_currency()).source(
            pid, dest_provider="kinguin", order_id=42
        )
        await s.commit()
        assert result.provider == "g2g"
        assert result.cost == Decimal("12.00")
        assert result.currency == "USD"
        assert result.code

    async with AsyncSessionLocal() as s:
        # Wallet debited by the native cost.
        wallet = (
            await s.execute(select(WalletBalance).where(WalletBalance.provider == "g2g"))
        ).scalar_one()
        assert Decimal(wallet.balance) == Decimal("88.00")
        # A JIT inventory row was created, reserved to the order.
        inv = (await s.execute(select(Inventory))).scalar_one()
        assert inv.status is InventoryStatus.RESERVED
        assert inv.reserved_order_id == 42
        assert Decimal(inv.source_cost) == Decimal("12.00")
        # The debit was recorded.
        tx = (
            await s.execute(
                select(Transaction).where(
                    Transaction.type == TransactionType.JIT_PURCHASE
                )
            )
        ).scalar_one()
        assert Decimal(tx.amount) == Decimal("-12.00")


@pytest.mark.asyncio
async def test_source_raises_when_wallet_underfunded() -> None:
    pid = await _seed()
    async with AsyncSessionLocal() as s:
        await WalletService(s).top_up("g2g", "USD", Decimal("5.00"))
        await s.commit()
    async with AsyncSessionLocal() as s:
        with pytest.raises(InsufficientFunds):
            await SourcingService(s, currency=_currency()).source(
                pid, dest_provider="kinguin", order_id=1
            )


@pytest.mark.asyncio
async def test_source_raises_when_no_supplier_available() -> None:
    async with AsyncSessionLocal() as s:
        for model in (MarketplacePrice, SkuMapping, Product):
            await s.execute(delete(model))
        await s.commit()
        product = Product(name="Lonely", internal_sku="LON-1")
        s.add(product)
        await s.flush()
        pid = product.id
        # Only the destination marketplace is mapped; no other source.
        s.add(SkuMapping(product_id=pid, marketplace="kinguin", marketplace_sku="K-1"))
        await s.commit()
    async with AsyncSessionLocal() as s:
        with pytest.raises(SourcingUnavailable):
            await SourcingService(s, currency=_currency()).source(
                pid, dest_provider="kinguin", order_id=1
            )
