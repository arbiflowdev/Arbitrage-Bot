"""Composite marketplace-fee resolution.

Each marketplace charges a *composite* fee (a percentage plus a fixed amount
per transaction) and a withdrawal/payout buffer. The adjustable defaults live
in settings (``.env``); an optional ``fee_structures`` row for a given
provider/category overrides them, which is the "category/platform tier table in
the database" the client asked for.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.pricing.engine import FeeParams


def default_fee_params(provider: str) -> FeeParams:
    """Composite fee parameters for ``provider`` from settings defaults."""
    d = settings.fee_defaults_for(provider)
    return FeeParams(
        sales_percent=d["sales_percent"],
        sales_fixed=d["sales_fixed"],
        withdrawal_percent=d["withdrawal_percent"],
        withdrawal_fixed=d["withdrawal_fixed"],
    )


class FeeService:
    def __init__(self, session: AsyncSession | None = None) -> None:
        self.session = session

    async def params_for(
        self, provider: str, category: str | None = None
    ) -> FeeParams:
        """Resolve fee parameters, preferring a DB override over config defaults.

        Resolution order: a ``fee_structures`` row matching (provider, category),
        then (provider, NULL = platform-wide), then the settings defaults.
        """
        if self.session is not None:
            # Imported lazily so the pure-config path has no DB dependency.
            from app.repositories.fee_structure_repository import (
                FeeStructureRepository,
            )

            row = await FeeStructureRepository(self.session).resolve(
                provider, category
            )
            if row is not None:
                return FeeParams(
                    sales_percent=Decimal(row.sales_percent) / Decimal("100"),
                    sales_fixed=Decimal(row.sales_fixed),
                    withdrawal_percent=Decimal(row.withdrawal_percent)
                    / Decimal("100"),
                    withdrawal_fixed=Decimal(row.withdrawal_fixed),
                )
        return default_fee_params(provider)
