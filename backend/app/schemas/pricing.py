"""Schemas for the arbitrage / pricing-engine API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ScanSummary(BaseModel):
    mode: str = Field(description="Active marketplace mode: 'mock' or 'live'.")
    dry_run: bool
    scanned: int = Field(ge=0, description="Listings examined.")
    decisions: int = Field(ge=0, description="Repricing decisions recorded.")
    applied: int = Field(ge=0, description="Prices actually pushed to a marketplace.")
    by_strategy: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class PricingStatus(BaseModel):
    enabled: bool = Field(description="Engine on/off (the kill-switch state).")
    dry_run: bool
    mode: str
    scan_interval_seconds: int
    base_currency: str
    min_profit_absolute: Decimal
    min_profit_margin_percent: Decimal
    undercut_amount: Decimal
    anomaly_drop: Decimal


class KillSwitch(BaseModel):
    enabled: bool = Field(description="Set False to halt all automated repricing.")


class RepricingHistoryRead(ORMModel):
    id: int
    provider: str
    marketplace_sku: str
    product_id: int | None = None
    listing_id: int | None = None
    strategy: str
    currency: str
    old_price: Decimal | None = None
    new_price: Decimal
    net_profit: Decimal
    margin: Decimal | None = None
    source_cost: Decimal | None = None
    sales_fee: Decimal | None = None
    withdrawal_fee: Decimal | None = None
    competitor_reference: Decimal | None = None
    anomaly_detected: bool
    changed: bool
    applied: bool
    dry_run: bool
    error: str | None = None
    notes: str | None = None
    created_at: datetime


class PricingSnapshotRead(ORMModel):
    id: int
    provider: str
    marketplace_sku: str
    product_id: int | None = None
    base_currency: str
    lowest_price: Decimal | None = None
    second_price: Decimal | None = None
    third_price: Decimal | None = None
    source_cost: Decimal | None = None
    competitor_count: int
    competitors: list | None = None
    created_at: datetime
