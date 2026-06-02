"""Inbound marketplace webhook events.

Every webhook a provider sends us is persisted here before processing. The
``(provider, external_id)`` pair gives idempotency: replays from the provider
are de-duplicated instead of being processed twice.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import JSONB, Base, TimestampedMixin


class WebhookEventStatus(str, enum.Enum):
    RECEIVED = "received"  # stored, not yet processed
    PROCESSED = "processed"  # handled successfully
    FAILED = "failed"  # handler raised; see error
    IGNORED = "ignored"  # known event type we intentionally skip


class WebhookEvent(TimestampedMixin, Base):
    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "external_id",
            name="uq_webhook_events_provider_external_id",
        ),
    )

    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # Provider-supplied unique id used for idempotency. Nullable because not
    # every provider sends one; multiple NULLs are allowed by the unique index.
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    signature_valid: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    status: Mapped[WebhookEventStatus] = mapped_column(
        Enum(
            WebhookEventStatus,
            name="webhook_event_status",
            native_enum=False,
            length=16,
        ),
        nullable=False,
        default=WebhookEventStatus.RECEIVED,
        server_default=WebhookEventStatus.RECEIVED.value,
        index=True,
    )
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    headers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
