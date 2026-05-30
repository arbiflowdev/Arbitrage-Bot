"""Credential storage for marketplace API integrations (Eneba, Kinguin, G2G, ...).

Secrets are stored as opaque strings in this milestone. Field-level
encryption is planned for a later milestone — keep secrets out of logs
and limit access via RBAC.
"""

from __future__ import annotations

from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import JSONB, Base, TimestampedMixin


class ApiCredential(TimestampedMixin, Base):
    __tablename__ = "api_credentials"
    __table_args__ = (
        UniqueConstraint("provider", "label", name="uq_api_credentials_provider_label"),
    )

    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="default",
        server_default="default",
    )
    api_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    api_secret: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
