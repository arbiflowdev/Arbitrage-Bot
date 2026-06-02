"""Marketplace-facing schemas: listings, prices, sync results, provider info."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.listing import ListingStatus
from app.schemas.common import ORMModel


class MarketplaceInfo(BaseModel):
    provider: str
    supported: bool
    mode: str = Field(description="Active mode: 'mock' or 'live'.")
    has_active_credential: bool


class MarketplacePriceRead(ORMModel):
    id: int
    provider: str
    marketplace_sku: str
    product_id: int | None = None
    currency: str
    price: Decimal
    available_qty: int | None = None
    is_available: bool
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime


class ListingRead(ORMModel):
    id: int
    provider: str
    marketplace_sku: str
    external_listing_id: str | None = None
    product_id: int | None = None
    title: str | None = None
    price: Decimal | None = None
    currency: str | None = None
    stock: int
    status: ListingStatus
    last_synced_at: datetime | None = None
    sync_error: str | None = None
    created_at: datetime
    updated_at: datetime


class SyncResult(BaseModel):
    provider: str
    operation: str = Field(description="e.g. 'prices' or 'listings'.")
    mode: str
    fetched: int = Field(ge=0, description="Records returned by the adapter.")
    upserted: int = Field(ge=0, description="Rows written to the database.")
    errors: list[str] = Field(default_factory=list)


class WebhookEventRead(ORMModel):
    id: int
    provider: str
    event_type: str
    external_id: str | None = None
    signature_valid: bool
    status: str
    error: str | None = None
    processed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class WebhookAck(BaseModel):
    received: bool
    status: str
    event_id: int | None = None
    detail: str | None = None
