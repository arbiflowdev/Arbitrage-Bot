"""Tests for the currency-conversion and fee-resolution layers."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.currency_service import CurrencyService
from app.services.fee_service import FeeService, default_fee_params

STATIC = {"EUR": Decimal("1"), "USD": Decimal("1.20")}


# ---------------------------------------------------------------------------
# Currency conversion
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_convert_between_currencies() -> None:
    svc = CurrencyService(
        base_currency="EUR", buffer_percent=Decimal("0"), static_rates=STATIC
    )
    # 12 USD -> EUR: 12 / 1.20 = 10
    assert await svc.convert(Decimal("12.00"), "USD", "EUR") == Decimal("10.00")
    # 10 EUR -> USD: 10 * 1.20 = 12
    assert await svc.convert(Decimal("10.00"), "EUR", "USD") == Decimal("12.00")


@pytest.mark.asyncio
async def test_to_base_applies_buffer_for_foreign_only() -> None:
    svc = CurrencyService(
        base_currency="EUR", buffer_percent=Decimal("1"), static_rates=STATIC
    )
    # 12 USD -> 10 EUR, + 1% FX buffer = 10.10
    assert await svc.to_base(Decimal("12.00"), "USD") == Decimal("10.10")
    # Already in base currency -> no conversion, no buffer.
    assert await svc.to_base(Decimal("10.00"), "EUR") == Decimal("10.00")


@pytest.mark.asyncio
async def test_unknown_currency_is_treated_as_base() -> None:
    svc = CurrencyService(
        base_currency="EUR", buffer_percent=Decimal("0"), static_rates=STATIC
    )
    # No rate for GBP -> conservatively pass through unchanged rather than crash.
    assert await svc.to_base(Decimal("7.00"), "GBP") == Decimal("7.00")


# ---------------------------------------------------------------------------
# Fee resolution (config defaults)
# ---------------------------------------------------------------------------
def test_default_fee_params_match_client_defaults() -> None:
    k = default_fee_params("kinguin")
    assert k.sales_percent == Decimal("0.11")
    assert k.sales_fixed == Decimal("0.35")

    g = default_fee_params("g2g")
    assert g.sales_percent == Decimal("0.099")
    assert g.sales_fixed == Decimal("0")

    e = default_fee_params("eneba")
    assert e.sales_percent == Decimal("0.12")
    assert e.sales_fixed == Decimal("0.30")


@pytest.mark.asyncio
async def test_fee_service_falls_back_to_config_without_db_row() -> None:
    # With no DB override, the service returns the config defaults.
    svc = FeeService(session=None)
    params = await svc.params_for("eneba")
    assert params.sales_percent == Decimal("0.12")
    assert params.sales_fixed == Decimal("0.30")
