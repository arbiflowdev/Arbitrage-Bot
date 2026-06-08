"""Tests for the M4 adapter fulfillment seam (purchase + deliver)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.integrations.kinguin import KinguinAdapter
from app.integrations.mock import MockAdapter


@pytest.mark.asyncio
async def test_mock_purchase_returns_deterministic_code_and_cost() -> None:
    adapter = MockAdapter("g2g")
    r1 = await adapter.purchase("SKU-1")
    r2 = await adapter.purchase("SKU-1")
    assert r1.code
    assert r1.code == r2.code  # deterministic for the same SKU
    assert r1.cost > Decimal("0")
    assert r1.external_purchase_id


@pytest.mark.asyncio
async def test_mock_deliver_succeeds() -> None:
    adapter = MockAdapter("kinguin")
    result = await adapter.deliver("order-1", "KEY-XYZ")
    assert result.success is True
    assert result.reference


@pytest.mark.asyncio
async def test_live_adapter_purchase_is_not_wired_yet() -> None:
    # Live per-marketplace purchase/deliver is deferred to live-credential
    # integration; the base default makes that explicit.
    adapter = KinguinAdapter()
    with pytest.raises(NotImplementedError):
        await adapter.purchase("SKU-1")
