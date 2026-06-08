"""Integration tests for WalletService (SQLite)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.fulfillment.exceptions import InsufficientFunds
from app.models.transaction import Transaction, TransactionType
from app.models.wallet_balance import WalletBalance
from app.services.wallet_service import WalletService


async def _reset() -> None:
    async with AsyncSessionLocal() as s:
        await s.execute(delete(Transaction))
        await s.execute(delete(WalletBalance))
        await s.commit()


@pytest.mark.asyncio
async def test_top_up_creates_wallet_and_records_transaction() -> None:
    await _reset()
    async with AsyncSessionLocal() as s:
        wallet = await WalletService(s).top_up("g2g", "EUR", Decimal("100.00"))
        await s.commit()
        assert Decimal(wallet.balance) == Decimal("100.00")

    async with AsyncSessionLocal() as s:
        tx = (
            await s.execute(select(Transaction).where(Transaction.provider == "g2g"))
        ).scalar_one()
        assert tx.type is TransactionType.TOP_UP
        assert Decimal(tx.amount) == Decimal("100.00")
        assert Decimal(tx.balance_after) == Decimal("100.00")


@pytest.mark.asyncio
async def test_debit_reduces_balance_and_records_negative_amount() -> None:
    await _reset()
    async with AsyncSessionLocal() as s:
        svc = WalletService(s)
        await svc.top_up("kinguin", "EUR", Decimal("50.00"))
        wallet = await svc.debit("kinguin", "EUR", Decimal("12.50"), order_id=7)
        await s.commit()
        assert Decimal(wallet.balance) == Decimal("37.50")

    async with AsyncSessionLocal() as s:
        debit_tx = (
            await s.execute(
                select(Transaction).where(
                    Transaction.type == TransactionType.JIT_PURCHASE
                )
            )
        ).scalar_one()
        assert Decimal(debit_tx.amount) == Decimal("-12.50")
        assert Decimal(debit_tx.balance_after) == Decimal("37.50")
        assert debit_tx.order_id == 7


@pytest.mark.asyncio
async def test_debit_beyond_balance_raises_insufficient_funds() -> None:
    await _reset()
    async with AsyncSessionLocal() as s:
        svc = WalletService(s)
        await svc.top_up("eneba", "EUR", Decimal("5.00"))
        await s.commit()
    async with AsyncSessionLocal() as s:
        with pytest.raises(InsufficientFunds):
            await WalletService(s).debit("eneba", "EUR", Decimal("9.99"))


@pytest.mark.asyncio
async def test_get_balance_is_zero_for_unknown_wallet() -> None:
    await _reset()
    async with AsyncSessionLocal() as s:
        assert await WalletService(s).get_balance("nope", "EUR") == Decimal("0")
