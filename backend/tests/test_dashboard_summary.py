"""GET /dashboard/summary aggregates orders, revenue, wallets, alerts, engine."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.order import Order, OrderStatus
from app.models.transaction import Transaction, TransactionType
from app.models.wallet_balance import WalletBalance


async def _seed() -> None:
    async with AsyncSessionLocal() as s:
        for m in (Transaction, WalletBalance, Order):
            await s.execute(delete(m))
        s.add(Order(provider="kinguin", external_order_id="D-1",
                    marketplace_sku="K", status=OrderStatus.DELIVERED))
        s.add(Order(provider="kinguin", external_order_id="D-2",
                    marketplace_sku="K", status=OrderStatus.FAILED))
        s.add(WalletBalance(provider="g2g", currency="EUR", balance=Decimal("100")))
        s.add(Transaction(type=TransactionType.SALE_REVENUE, provider="kinguin",
                          amount=Decimal("20.00"), currency="EUR",
                          balance_after=Decimal("20.00")))
        await s.commit()


@pytest.mark.asyncio
async def test_summary_requires_admin(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/dashboard/summary")).status_code == 401


@pytest.mark.asyncio
async def test_summary_shape(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    await _seed()
    resp = await client.get("/api/v1/dashboard/summary", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["orders"]["delivered"] >= 1
    assert body["orders"]["failed"] >= 1
    assert Decimal(body["revenue_today"]) >= Decimal("20.00")
    assert body["wallet_total"] is not None
    assert "pricing_enabled" in body["engine"]
