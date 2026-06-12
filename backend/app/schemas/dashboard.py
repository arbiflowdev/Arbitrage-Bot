"""Schemas for the Milestone 5 dashboard, products, alerts, logs, and system."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    internal_sku: str
    name: str
    platform: str | None = None
    region: str | None = None
    is_active: bool
    created_at: datetime


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    severity: str
    status: str
    title: str
    message: str
    provider: str | None = None
    order_id: int | None = None
    created_at: datetime
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None

    @field_validator("type", "severity", "status", mode="before")
    @classmethod
    def _enum_value(cls, v: object) -> object:
        return v.value if hasattr(v, "value") else v


class AlertSummary(BaseModel):
    info: int = 0
    warning: int = 0
    critical: int = 0


class LogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    level: str
    source: str
    message: str
    context: dict | None = None
    created_at: datetime

    @field_validator("level", mode="before")
    @classmethod
    def _level_value(cls, v: object) -> object:
        return v.value if hasattr(v, "value") else v


class SystemStatus(BaseModel):
    pricing_enabled: bool
    fulfillment_enabled: bool
    mode: str
    dry_run: bool


class KillSwitchRequest(BaseModel):
    enabled: bool


class DashboardSummary(BaseModel):
    orders: dict[str, int]
    revenue_today: Decimal
    delivered_today: int
    inventory_available: int
    wallet_total: Decimal
    wallets: list[dict]
    alerts: dict[str, int]
    engine: dict
