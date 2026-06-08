"""Transaction (ledger) data access."""

from __future__ import annotations

from sqlalchemy import select

from app.models.transaction import Transaction, TransactionType
from app.repositories.base import BaseRepository


class TransactionRepository(BaseRepository[Transaction]):
    model = Transaction

    async def list_recent(
        self,
        provider: str | None = None,
        *,
        type: TransactionType | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Transaction]:
        stmt = select(Transaction)
        if provider is not None:
            stmt = stmt.where(Transaction.provider == provider)
        if type is not None:
            stmt = stmt.where(Transaction.type == type)
        stmt = stmt.order_by(Transaction.id.desc()).limit(limit).offset(offset)
        result = await self.session.scalars(stmt)
        return list(result.all())
