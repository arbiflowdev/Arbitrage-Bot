"""Wallet balance data access with row-level locking for safe debits."""

from __future__ import annotations

from sqlalchemy import select

from app.models.wallet_balance import WalletBalance
from app.repositories.base import BaseRepository


class WalletRepository(BaseRepository[WalletBalance]):
    model = WalletBalance

    @property
    def _is_postgres(self) -> bool:
        bind = self.session.bind
        return bool(bind is not None and bind.dialect.name == "postgresql")

    async def get(self, provider: str, currency: str) -> WalletBalance | None:
        return await self.session.scalar(
            select(WalletBalance).where(
                WalletBalance.provider == provider,
                WalletBalance.currency == currency,
            )
        )

    async def get_for_update(
        self, provider: str, currency: str
    ) -> WalletBalance | None:
        """Fetch a wallet row locked ``FOR UPDATE`` (PostgreSQL only)."""
        stmt = select(WalletBalance).where(
            WalletBalance.provider == provider,
            WalletBalance.currency == currency,
        )
        if self._is_postgres:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def list_all(self) -> list[WalletBalance]:
        result = await self.session.scalars(
            select(WalletBalance).order_by(WalletBalance.provider, WalletBalance.currency)
        )
        return list(result.all())
