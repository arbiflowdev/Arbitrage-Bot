"""Operational alerts surfaced on the dashboard.

An alert represents a condition an operator should see: a failed order, a
low wallet balance, an order stuck awaiting stock, or an engine/worker issue.
``dedupe_key`` lets a recurring condition update one OPEN alert instead of
spawning duplicates; it is cleared/resolved when the condition clears.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import JSONB, PK_TYPE, Base, TimestampedMixin


class AlertType(str, enum.Enum):
    ORDER_FAILED = "order_failed"
    LOW_WALLET = "low_wallet"
    AWAITING_STOCK = "awaiting_stock"
    ENGINE_ISSUE = "engine_issue"


class AlertSeverity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertStatus(str, enum.Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class Alert(TimestampedMixin, Base):
    __tablename__ = "alerts"

    type: Mapped[AlertType] = mapped_column(
        Enum(AlertType, name="alert_type", native_enum=False, length=20),
        nullable=False,
        index=True,
    )
    severity: Mapped[AlertSeverity] = mapped_column(
        Enum(AlertSeverity, name="alert_severity", native_enum=False, length=10),
        nullable=False,
    )
    status: Mapped[AlertStatus] = mapped_column(
        Enum(AlertStatus, name="alert_status", native_enum=False, length=12),
        nullable=False,
        default=AlertStatus.OPEN,
        server_default="open",
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(String(2000), nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    order_id: Mapped[int | None] = mapped_column(
        PK_TYPE,
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
