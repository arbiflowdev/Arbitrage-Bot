"""Pydantic schemas for the Milestone 4 fulfillment API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class InventoryUploadRequest(BaseModel):
    product_id: int
    format: str = "txt"
    content: str


class UploadSummary(BaseModel):
    added: int
    duplicates: int
    skipped: int
    batch_id: str


class InventoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int | None
    code_masked: str
    status: str
    region: str | None
    platform: str | None
    source_cost: Decimal | None
    currency: str | None
    reserved_order_id: int | None
    batch_id: str | None
    created_at: datetime


class InventorySummary(BaseModel):
    product_id: int | None = None
    available: int = 0
    reserved: int = 0
    sold: int = 0
    invalid: int = 0


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    external_order_id: str
    marketplace_sku: str
    product_id: int | None
    quantity: int
    total: Decimal | None
    currency: str | None
    status: str
    fulfillment_source: str | None
    inventory_id: int | None
    attempts: int
    last_error: str | None
    delivered_at: datetime | None
    created_at: datetime


class OrderIngestRequest(BaseModel):
    provider: str
    external_order_id: str
    marketplace_sku: str
    quantity: int = 1
    total: Decimal | None = None
    currency: str | None = None


class WalletRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    currency: str
    balance: Decimal


class TopUpRequest(BaseModel):
    provider: str
    currency: str
    amount: Decimal = Field(gt=0)
    notes: str | None = None


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int | None
    type: str
    provider: str | None
    amount: Decimal
    currency: str
    balance_after: Decimal | None
    reference: str | None
    notes: str | None
    created_at: datetime
