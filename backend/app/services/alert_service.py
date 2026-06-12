"""Alert service — raise, dedupe, list, acknowledge, resolve, and scan.

Raising with a ``dedupe_key`` updates the existing OPEN alert (if any) instead
of inserting a duplicate, so a recurring condition shows as one live alert.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.alert import Alert, AlertSeverity, AlertStatus, AlertType
from app.repositories.alert_repository import AlertRepository
from app.repositories.wallet_repository import WalletRepository
from app.services.currency_service import CurrencyService
from app.utils.datetime import utcnow

log = get_logger(__name__)


class AlertService:
    def __init__(
        self, session: AsyncSession, *, currency: CurrencyService | None = None
    ) -> None:
        self.session = session
        self.repo = AlertRepository(session)
        self.currency = currency or CurrencyService()

    async def raise_alert(
        self,
        type: AlertType,
        severity: AlertSeverity,
        title: str,
        message: str,
        *,
        dedupe_key: str | None = None,
        provider: str | None = None,
        order_id: int | None = None,
        context: dict | None = None,
    ) -> Alert:
        if not settings.ALERTS_ENABLED:
            # Still return a transient object so callers don't special-case.
            return Alert(
                type=type, severity=severity, status=AlertStatus.OPEN,
                title=title, message=message,
            )
        existing = (
            await self.repo.get_open_by_dedupe(dedupe_key) if dedupe_key else None
        )
        if existing is not None:
            existing.severity = severity
            existing.title = title
            existing.message = message
            existing.provider = provider
            existing.order_id = order_id
            existing.context = context
            await self.session.flush()
            return existing
        alert = Alert(
            type=type,
            severity=severity,
            status=AlertStatus.OPEN,
            title=title,
            message=message,
            dedupe_key=dedupe_key,
            provider=provider,
            order_id=order_id,
            context=context,
        )
        return await self.repo.add(alert)

    async def list(
        self,
        status: AlertStatus | None = None,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Alert]:
        return await self.repo.list_by_status(status, limit=limit, offset=offset)

    async def acknowledge(self, alert_id: int) -> Alert | None:
        alert = await self.repo.get_by_id(alert_id)
        if alert is None:
            return None
        alert.status = AlertStatus.ACKNOWLEDGED
        alert.acknowledged_at = utcnow()
        await self.session.flush()
        return alert

    async def resolve(self, alert_id: int) -> Alert | None:
        alert = await self.repo.get_by_id(alert_id)
        if alert is None:
            return None
        alert.status = AlertStatus.RESOLVED
        alert.resolved_at = utcnow()
        await self.session.flush()
        return alert

    async def resolve_by_dedupe(self, dedupe_key: str) -> None:
        alert = await self.repo.get_open_by_dedupe(dedupe_key)
        if alert is not None:
            alert.status = AlertStatus.RESOLVED
            alert.resolved_at = utcnow()
            await self.session.flush()

    async def summary(self) -> dict[str, int]:
        return await self.repo.count_open_by_severity()

    async def check_low_wallets(self, threshold: Decimal | None = None) -> list[Alert]:
        limit = threshold if threshold is not None else settings.ALERT_LOW_WALLET_THRESHOLD
        wallets = await WalletRepository(self.session).list_all()
        raised: list[Alert] = []
        for w in wallets:
            base = await self.currency.to_base(Decimal(w.balance), w.currency)
            if base < Decimal(limit):
                alert = await self.raise_alert(
                    AlertType.LOW_WALLET,
                    AlertSeverity.WARNING,
                    f"Low balance: {w.provider}",
                    f"{w.provider}/{w.currency} balance {w.balance} "
                    f"(~{base} base) is below {limit}.",
                    dedupe_key=f"low-wallet-{w.provider}-{w.currency}",
                    provider=w.provider,
                    context={"balance": str(w.balance), "currency": w.currency},
                )
                raised.append(alert)
        return raised
