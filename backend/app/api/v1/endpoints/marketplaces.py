"""Marketplace operations endpoints (admin only).

Manual sync triggers + read access to synced data. Automated/scheduled scans
are a Milestone-3 concern; here an operator runs syncs on demand.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body

from app.core.dependencies import CurrentAdmin, SessionDep
from app.schemas.marketplace import (
    ListingRead,
    MarketplaceInfo,
    MarketplacePriceRead,
    SyncResult,
)
from app.services.marketplace_service import MarketplaceService

router = APIRouter(tags=["marketplaces"])


@router.get(
    "/marketplaces",
    response_model=list[MarketplaceInfo],
    summary="List supported marketplaces and their status",
)
async def list_marketplaces(
    _: CurrentAdmin, session: SessionDep
) -> list[MarketplaceInfo]:
    return await MarketplaceService(session).list_marketplaces()


@router.post(
    "/marketplaces/{provider}/sync/prices",
    response_model=SyncResult,
    summary="Fetch and store current marketplace prices",
)
async def sync_prices(
    provider: str,
    _: CurrentAdmin,
    session: SessionDep,
    skus: Annotated[
        list[str] | None,
        Body(
            embed=True,
            description="Optional list of marketplace SKUs to restrict the sync.",
        ),
    ] = None,
) -> SyncResult:
    return await MarketplaceService(session).sync_prices(provider, skus)


@router.post(
    "/marketplaces/{provider}/sync/listings",
    response_model=SyncResult,
    summary="Fetch and store our listings on a marketplace",
)
async def sync_listings(
    provider: str,
    _: CurrentAdmin,
    session: SessionDep,
) -> SyncResult:
    return await MarketplaceService(session).sync_listings(provider)


@router.get(
    "/marketplaces/{provider}/orders",
    summary="Fetch recent orders from a marketplace (live read)",
)
async def fetch_orders(
    provider: str,
    _: CurrentAdmin,
    session: SessionDep,
    limit: int = 50,
    page: int = 1,
) -> list[dict]:
    return await MarketplaceService(session).fetch_orders(
        provider, limit=limit, page=page
    )


@router.get(
    "/marketplace-prices",
    response_model=list[MarketplacePriceRead],
    summary="List stored marketplace prices",
)
async def list_prices(
    _: CurrentAdmin,
    session: SessionDep,
    provider: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[MarketplacePriceRead]:
    rows = await MarketplaceService(session).list_prices(
        provider, limit=limit, offset=offset
    )
    return [MarketplacePriceRead.model_validate(r) for r in rows]


@router.get(
    "/listings",
    response_model=list[ListingRead],
    summary="List stored marketplace listings",
)
async def list_listings(
    _: CurrentAdmin,
    session: SessionDep,
    provider: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ListingRead]:
    rows = await MarketplaceService(session).list_listings(
        provider, limit=limit, offset=offset
    )
    return [ListingRead.model_validate(r) for r in rows]
