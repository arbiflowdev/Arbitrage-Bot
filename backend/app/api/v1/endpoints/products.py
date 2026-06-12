"""Product catalogue endpoints (admin only)."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.dependencies import CurrentAdmin, SessionDep
from app.repositories.product_repository import ProductRepository
from app.schemas.dashboard import ProductRead

router = APIRouter(tags=["products"])


@router.get(
    "/products",
    response_model=list[ProductRead],
    summary="List products in the catalogue",
)
async def list_products(
    _: CurrentAdmin,
    session: SessionDep,
    limit: int = 100,
    offset: int = 0,
) -> list[ProductRead]:
    rows = await ProductRepository(session).list(limit=limit, offset=offset)
    return [ProductRead.model_validate(r) for r in rows]
