"""Product catalogue endpoints (admin only).

A Product is the internal catalogue item; SkuMappings link it to each
marketplace's SKU. Operators create and manage both here so the platform is
usable without touching the database directly.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from app.core.dependencies import CurrentAdmin, SessionDep
from app.integrations import SUPPORTED_PROVIDERS, is_supported
from app.models.product import Product
from app.models.sku_mapping import SkuMapping
from app.repositories.product_repository import ProductRepository
from app.repositories.sku_mapping_repository import SkuMappingRepository
from app.schemas.dashboard import (
    ProductCreate,
    ProductRead,
    ProductUpdate,
    SkuMappingCreate,
    SkuMappingRead,
)

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


@router.post(
    "/products",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a catalogue product",
)
async def create_product(
    payload: ProductCreate,
    _: CurrentAdmin,
    session: SessionDep,
) -> ProductRead:
    repo = ProductRepository(session)
    if await repo.get_by_internal_sku(payload.internal_sku):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A product with internal_sku '{payload.internal_sku}' exists.",
        )
    product = Product(**payload.model_dump())
    await repo.add(product)
    await session.commit()
    await session.refresh(product)
    return ProductRead.model_validate(product)


@router.patch(
    "/products/{product_id}",
    response_model=ProductRead,
    summary="Update a catalogue product",
)
async def update_product(
    product_id: int,
    payload: ProductUpdate,
    _: CurrentAdmin,
    session: SessionDep,
) -> ProductRead:
    repo = ProductRepository(session)
    product = await repo.get_by_id(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    data = payload.model_dump(exclude_unset=True)
    if data:
        await repo.update(product, data)
        await session.commit()
        await session.refresh(product)
    return ProductRead.model_validate(product)


@router.get(
    "/products/{product_id}/mappings",
    response_model=list[SkuMappingRead],
    summary="List a product's marketplace SKU mappings",
)
async def list_mappings(
    product_id: int,
    _: CurrentAdmin,
    session: SessionDep,
) -> list[SkuMappingRead]:
    rows = await SkuMappingRepository(session).list_for_product(product_id)
    return [SkuMappingRead.model_validate(r) for r in rows]


@router.post(
    "/products/{product_id}/mappings",
    response_model=SkuMappingRead,
    status_code=status.HTTP_201_CREATED,
    summary="Link a product to a marketplace SKU",
)
async def create_mapping(
    product_id: int,
    payload: SkuMappingCreate,
    _: CurrentAdmin,
    session: SessionDep,
) -> SkuMappingRead:
    product = await ProductRepository(session).get_by_id(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")

    marketplace = payload.marketplace.lower()
    if not is_supported(marketplace):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown marketplace '{marketplace}'. Supported: "
            f"{', '.join(SUPPORTED_PROVIDERS)}.",
        )

    repo = SkuMappingRepository(session)
    existing = await repo.get_by_marketplace_sku(marketplace, payload.marketplace_sku)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"SKU '{payload.marketplace_sku}' is already mapped on "
            f"{marketplace}.",
        )

    mapping = SkuMapping(
        product_id=product_id,
        marketplace=marketplace,
        marketplace_sku=payload.marketplace_sku,
        marketplace_url=payload.marketplace_url,
    )
    await repo.add(mapping)
    await session.commit()
    await session.refresh(mapping)
    return SkuMappingRead.model_validate(mapping)


@router.delete(
    "/products/{product_id}/mappings/{mapping_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a marketplace SKU mapping",
)
async def delete_mapping(
    product_id: int,
    mapping_id: int,
    _: CurrentAdmin,
    session: SessionDep,
) -> Response:
    repo = SkuMappingRepository(session)
    mapping = await repo.get_by_id(mapping_id)
    if mapping is None or mapping.product_id != product_id:
        raise HTTPException(status_code=404, detail="Mapping not found.")
    await repo.delete(mapping_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
