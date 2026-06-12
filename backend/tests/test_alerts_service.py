"""Unit tests for AlertService: dedupe, lifecycle, low-wallet scan."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.alert import Alert, AlertSeverity, AlertStatus, AlertType
from app.models.wallet_balance import WalletBalance
from app.services.alert_service import AlertService
from app.services.currency_service import CurrencyService


async def _clear() -> None:
    async with AsyncSessionLocal() as s:
        await s.execute(delete(Alert))
        await s.execute(delete(WalletBalance))
        await s.commit()


@pytest.mark.asyncio
async def test_raise_dedupes_open_alert() -> None:
    await _clear()
    async with AsyncSessionLocal() as s:
        svc = AlertService(s)
        a1 = await svc.raise_alert(
            AlertType.ORDER_FAILED, AlertSeverity.CRITICAL,
            "Order failed", "boom", dedupe_key="order-failed-1",
        )
        a2 = await svc.raise_alert(
            AlertType.ORDER_FAILED, AlertSeverity.CRITICAL,
            "Order failed again", "boom2", dedupe_key="order-failed-1",
        )
        await s.commit()
        assert a1.id == a2.id  # same row updated, not duplicated
        assert a2.message == "boom2"
        rows = await svc.list(status=AlertStatus.OPEN)
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_acknowledge_and_resolve() -> None:
    await _clear()
    async with AsyncSessionLocal() as s:
        svc = AlertService(s)
        a = await svc.raise_alert(
            AlertType.ENGINE_ISSUE, AlertSeverity.WARNING, "t", "m"
        )
        await s.commit()
        await svc.acknowledge(a.id)
        await s.commit()
        assert (await svc.repo.get_by_id(a.id)).status == AlertStatus.ACKNOWLEDGED
        await svc.resolve(a.id)
        await s.commit()
        assert (await svc.repo.get_by_id(a.id)).status == AlertStatus.RESOLVED


@pytest.mark.asyncio
async def test_low_wallet_scan_raises_once() -> None:
    await _clear()
    async with AsyncSessionLocal() as s:
        s.add(WalletBalance(provider="g2g", currency="EUR", balance=Decimal("5")))
        s.add(WalletBalance(provider="kinguin", currency="EUR", balance=Decimal("500")))
        await s.commit()
    async with AsyncSessionLocal() as s:
        svc = AlertService(s, currency=CurrencyService(static_rates={"EUR": 1}))
        raised = await svc.check_low_wallets(threshold=Decimal("25"))
        await s.commit()
        assert len(raised) == 1
        assert raised[0].provider == "g2g"
        # Re-running does not duplicate (dedupe on the OPEN alert).
        again = await svc.check_low_wallets(threshold=Decimal("25"))
        await s.commit()
        assert len(again) == 1  # updated, still one OPEN alert
        assert len(await svc.list(status=AlertStatus.OPEN)) == 1
