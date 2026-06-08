"""Wallet service — funds used to pay for just-in-time purchases.

Balances are held per ``(provider, currency)`` and mutated under a row lock so
concurrent fulfillment workers can never double-spend. Every movement writes a
signed :class:`Transaction` (credit positive, debit negative) with the resulting
balance, giving a complete audit trail.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.fulfillment.exceptions import InsufficientFunds
from app.models.transaction import Transaction, TransactionType
from app.models.wallet_balance import WalletBalance
from app.repositories.wallet_repository import WalletRepository

log = get_logger(__name__)

_CENT = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_CENT)


class WalletService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = WalletRepository(session)

    async def get_balance(self, provider: str, currency: str) -> Decimal:
        wallet = await self.repo.get(provider, currency)
        return Decimal(wallet.balance) if wallet is not None else Decimal("0")

    async def top_up(
        self,
        provider: str,
        currency: str,
        amount: Decimal,
        *,
        notes: str | None = None,
    ) -> WalletBalance:
        return await self.credit(
            provider,
            currency,
            amount,
            type=TransactionType.TOP_UP,
            notes=notes,
        )

    async def credit(
        self,
        provider: str,
        currency: str,
        amount: Decimal,
        *,
        order_id: int | None = None,
        type: TransactionType = TransactionType.SALE_REVENUE,
        reference: str | None = None,
        notes: str | None = None,
    ) -> WalletBalance:
        amount = _q(amount)
        wallet = await self._get_or_create(provider, currency)
        wallet.balance = _q(Decimal(wallet.balance) + amount)
        self._record(wallet, amount, type, order_id, reference, notes)
        await self.session.flush()
        return wallet

    async def debit(
        self,
        provider: str,
        currency: str,
        amount: Decimal,
        *,
        order_id: int | None = None,
        type: TransactionType = TransactionType.JIT_PURCHASE,
        reference: str | None = None,
        notes: str | None = None,
    ) -> WalletBalance:
        amount = _q(amount)
        wallet = await self._get_or_create(provider, currency)
        current = Decimal(wallet.balance)
        if settings.WALLET_ENFORCE and amount > current:
            raise InsufficientFunds(
                f"{provider}/{currency} balance {current} < required {amount}."
            )
        wallet.balance = _q(current - amount)
        self._record(wallet, -amount, type, order_id, reference, notes)
        await self.session.flush()
        return wallet

    # ---- internals --------------------------------------------------------
    async def _get_or_create(self, provider: str, currency: str) -> WalletBalance:
        wallet = await self.repo.get_for_update(provider, currency)
        if wallet is None:
            wallet = WalletBalance(provider=provider, currency=currency, balance=0)
            self.session.add(wallet)
            await self.session.flush()
        return wallet

    def _record(
        self,
        wallet: WalletBalance,
        amount: Decimal,
        type: TransactionType,
        order_id: int | None,
        reference: str | None,
        notes: str | None,
    ) -> None:
        self.session.add(
            Transaction(
                order_id=order_id,
                type=type,
                provider=wallet.provider,
                amount=amount,
                currency=wallet.currency,
                balance_after=Decimal(wallet.balance),
                reference=reference,
                notes=notes,
            )
        )
