"""Hybrid inventory & fulfillment endpoints (admin only).

Operators stock manual inventory (TXT/CSV), watch orders flow through the
inventory-first / JIT pipeline, fund and monitor marketplace wallets, and audit
the transaction ledger. Deliverable codes are always masked in responses.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Query, status

from app.core.dependencies import CurrentAdmin, SessionDep
from app.models.inventory import Inventory, InventoryStatus
from app.models.order import OrderStatus
from app.models.transaction import TransactionType
from app.repositories.inventory_repository import InventoryRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.transaction_repository import TransactionRepository
from app.repositories.wallet_repository import WalletRepository
from app.schemas.fulfillment import (
    InventoryRead,
    InventorySummary,
    InventoryUploadRequest,
    OrderIngestRequest,
    OrderRead,
    TopUpRequest,
    TransactionRead,
    UploadSummary,
    WalletRead,
)
from app.services.fulfillment_service import FulfillmentService
from app.services.inventory_service import InventoryService
from app.services.order_intake_service import OrderIntakeService
from app.services.wallet_service import WalletService

router = APIRouter(tags=["fulfillment"])


def _mask(code: str) -> str:
    if len(code) <= 4:
        return "*" * len(code)
    return "****" + code[-4:]


def _inventory_read(row: Inventory) -> InventoryRead:
    return InventoryRead(
        id=row.id,
        product_id=row.product_id,
        code_masked=_mask(row.code),
        status=row.status.value,
        region=row.region,
        platform=row.platform,
        source_cost=row.source_cost,
        currency=row.currency,
        reserved_order_id=row.reserved_order_id,
        batch_id=row.batch_id,
        created_at=row.created_at,
    )


# ---- inventory ------------------------------------------------------------
@router.post(
    "/inventory/upload",
    response_model=UploadSummary,
    summary="Bulk-upload deliverable codes (TXT/CSV) for a product",
)
async def upload_inventory(
    _: CurrentAdmin,
    session: SessionDep,
    payload: Annotated[InventoryUploadRequest, Body()],
) -> UploadSummary:
    try:
        summary = await InventoryService(session).upload(
            payload.product_id, payload.content, payload.format
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    await session.commit()
    return summary


@router.get(
    "/inventory",
    response_model=list[InventoryRead],
    summary="List inventory for a product (codes masked)",
)
async def list_inventory(
    _: CurrentAdmin,
    session: SessionDep,
    product_id: int,
    status_filter: Annotated[InventoryStatus | None, Query(alias="status")] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[InventoryRead]:
    rows = await InventoryRepository(session).list_for_product(
        product_id, status=status_filter, limit=limit, offset=offset
    )
    return [_inventory_read(r) for r in rows]


@router.get(
    "/inventory/summary",
    response_model=InventorySummary,
    summary="Per-status inventory counts for a product",
)
async def inventory_summary(
    _: CurrentAdmin, session: SessionDep, product_id: int
) -> InventorySummary:
    repo = InventoryRepository(session)
    return InventorySummary(
        product_id=product_id,
        available=await repo.count_status(product_id, InventoryStatus.AVAILABLE),
        reserved=await repo.count_status(product_id, InventoryStatus.RESERVED),
        sold=await repo.count_status(product_id, InventoryStatus.SOLD),
        invalid=await repo.count_status(product_id, InventoryStatus.INVALID),
    )


@router.post(
    "/inventory/{inventory_id}/invalidate",
    response_model=InventoryRead,
    summary="Mark an inventory code invalid (e.g. dead key)",
)
async def invalidate_inventory(
    _: CurrentAdmin, session: SessionDep, inventory_id: int
) -> InventoryRead:
    try:
        row = await InventoryService(session).invalidate(inventory_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    await session.commit()
    return _inventory_read(row)


# ---- orders ---------------------------------------------------------------
@router.get(
    "/orders",
    response_model=list[OrderRead],
    summary="List orders (most recent first)",
)
async def list_orders(
    _: CurrentAdmin,
    session: SessionDep,
    provider: str | None = None,
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[OrderRead]:
    rows = await OrderRepository(session).list_recent(
        provider, status=status_filter, limit=limit, offset=offset
    )
    return [OrderRead.model_validate(r) for r in rows]


@router.get(
    "/orders/{order_id}",
    response_model=OrderRead,
    summary="Get a single order",
)
async def get_order(
    _: CurrentAdmin, session: SessionDep, order_id: int
) -> OrderRead:
    row = await OrderRepository(session).get_by_id(order_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
        )
    return OrderRead.model_validate(row)


@router.post(
    "/orders/ingest",
    response_model=OrderRead,
    summary="Ingest an order and attempt fulfillment now (manual/testing)",
)
async def ingest_order(
    _: CurrentAdmin,
    session: SessionDep,
    payload: Annotated[OrderIngestRequest, Body()],
) -> OrderRead:
    order, _created = await OrderIntakeService(session).ingest(
        payload.provider,
        payload.external_order_id,
        payload.marketplace_sku,
        quantity=payload.quantity,
        total=payload.total,
        currency=payload.currency,
    )
    await session.commit()
    await FulfillmentService(session).fulfill(order.id)
    refreshed = await OrderRepository(session).get_by_id(order.id)
    return OrderRead.model_validate(refreshed)


@router.post(
    "/orders/{order_id}/retry",
    response_model=OrderRead,
    summary="Re-attempt fulfillment for an order",
)
async def retry_order(
    _: CurrentAdmin, session: SessionDep, order_id: int
) -> OrderRead:
    if await OrderRepository(session).get_by_id(order_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
        )
    await FulfillmentService(session).fulfill(order_id)
    refreshed = await OrderRepository(session).get_by_id(order_id)
    return OrderRead.model_validate(refreshed)


# ---- wallet + ledger ------------------------------------------------------
@router.get(
    "/wallet",
    response_model=list[WalletRead],
    summary="List marketplace wallet balances",
)
async def list_wallets(_: CurrentAdmin, session: SessionDep) -> list[WalletRead]:
    rows = await WalletRepository(session).list_all()
    return [WalletRead.model_validate(r) for r in rows]


@router.post(
    "/wallet/top-up",
    response_model=WalletRead,
    summary="Add funds to a marketplace wallet",
)
async def top_up_wallet(
    _: CurrentAdmin,
    session: SessionDep,
    payload: Annotated[TopUpRequest, Body()],
) -> WalletRead:
    wallet = await WalletService(session).top_up(
        payload.provider, payload.currency, payload.amount, notes=payload.notes
    )
    await session.commit()
    return WalletRead.model_validate(wallet)


@router.get(
    "/transactions",
    response_model=list[TransactionRead],
    summary="Recent ledger transactions (most recent first)",
)
async def list_transactions(
    _: CurrentAdmin,
    session: SessionDep,
    provider: str | None = None,
    type_filter: Annotated[TransactionType | None, Query(alias="type")] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[TransactionRead]:
    rows = await TransactionRepository(session).list_recent(
        provider, type=type_filter, limit=limit, offset=offset
    )
    return [TransactionRead.model_validate(r) for r in rows]
