"""Repository for composite-fee overrides."""

from __future__ import annotations

from sqlalchemy import select

from app.models.fee_structure import FeeStructure
from app.repositories.base import BaseRepository


class FeeStructureRepository(BaseRepository[FeeStructure]):
    model = FeeStructure

    async def resolve(
        self, provider: str, category: str | None = None
    ) -> FeeStructure | None:
        """Most-specific active override: (provider, category) then (provider)."""
        if category is not None:
            stmt = select(FeeStructure).where(
                FeeStructure.provider == provider,
                FeeStructure.category == category,
                FeeStructure.is_active.is_(True),
            )
            row = await self.session.scalar(stmt)
            if row is not None:
                return row
        stmt = select(FeeStructure).where(
            FeeStructure.provider == provider,
            FeeStructure.category.is_(None),
            FeeStructure.is_active.is_(True),
        )
        return await self.session.scalar(stmt)
