"""Marketplace service — the unified abstraction layer.

Resolves credentials, builds the right adapter (mock or live), runs sync
operations, and persists normalized results. API endpoints call this service
and never touch adapters directly.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations import (
    SUPPORTED_PROVIDERS,
    MarketplaceAdapter,
    build_adapter,
    is_supported,
    resolve_credentials,
)
from app.integrations.exceptions import (
    CredentialsNotConfigured,
    IntegrationError,
    ProviderAPIError,
    ProviderUnavailable,
    RateLimitExceeded,
)
from app.models.listing import ListingStatus
from app.repositories.listing_repository import ListingRepository
from app.repositories.marketplace_price_repository import MarketplacePriceRepository
from app.schemas.marketplace import MarketplaceInfo, SyncResult
from app.utils.datetime import utcnow

log = get_logger(__name__)


def _raise_http_from_integration(provider: str, exc: IntegrationError) -> None:
    """Translate a provider integration error into an HTTP error."""
    if isinstance(exc, CredentialsNotConfigured):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"No API credential for '{provider}'. Paste keys into .env "
                f"({provider.upper()}_API_KEY) and set MARKETPLACE_MODE=live, "
                f"or run in mock mode."
            ),
        ) from exc
    if isinstance(exc, RateLimitExceeded):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        ) from exc
    if isinstance(exc, ProviderUnavailable | ProviderAPIError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
    ) from exc


def _map_status(value: str) -> ListingStatus:
    try:
        return ListingStatus(value)
    except ValueError:
        return ListingStatus.ACTIVE


class MarketplaceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.prices = MarketplacePriceRepository(session)
        self.listings = ListingRepository(session)

    def _require_supported(self, provider: str) -> None:
        if not is_supported(provider):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"Unknown provider '{provider}'. Supported: "
                    f"{', '.join(SUPPORTED_PROVIDERS)}."
                ),
            )

    async def _adapter(self, provider: str) -> MarketplaceAdapter:
        self._require_supported(provider)
        creds = resolve_credentials(provider)
        return build_adapter(provider, creds)

    # ---- discovery --------------------------------------------------------
    async def list_marketplaces(self) -> list[MarketplaceInfo]:
        infos: list[MarketplaceInfo] = []
        for provider in SUPPORTED_PROVIDERS:
            # Reflect whether live keys are present in .env for this provider.
            creds = resolve_credentials(provider)
            infos.append(
                MarketplaceInfo(
                    provider=provider,
                    supported=True,
                    mode=settings.MARKETPLACE_MODE,
                    has_active_credential=bool(creds and creds.api_key),
                )
            )
        return infos

    # ---- sync operations --------------------------------------------------
    async def sync_prices(
        self, provider: str, skus: list[str] | None = None
    ) -> SyncResult:
        adapter = await self._adapter(provider)
        try:
            fetched = await adapter.fetch_prices(skus)
        except IntegrationError as exc:
            _raise_http_from_integration(provider, exc)
        finally:
            await adapter.aclose()

        now = utcnow()
        errors: list[str] = []
        upserted = 0
        for price in fetched:
            try:
                await self.prices.upsert(
                    provider,
                    price.marketplace_sku,
                    {
                        "currency": price.currency,
                        "price": price.price,
                        "available_qty": price.available_qty,
                        "is_available": price.is_available,
                        "raw": price.raw,
                        "fetched_at": now,
                    },
                )
                upserted += 1
            except Exception as exc:  # noqa: BLE001 — isolate one bad record
                errors.append(f"{price.marketplace_sku}: {exc}")
        await self.session.commit()
        log.info(
            "marketplace.sync_prices",
            provider=provider,
            fetched=len(fetched),
            upserted=upserted,
        )
        return SyncResult(
            provider=provider,
            operation="prices",
            mode=settings.MARKETPLACE_MODE,
            fetched=len(fetched),
            upserted=upserted,
            errors=errors,
        )

    async def sync_listings(self, provider: str) -> SyncResult:
        adapter = await self._adapter(provider)
        try:
            fetched = await adapter.fetch_listings()
        except IntegrationError as exc:
            _raise_http_from_integration(provider, exc)
        finally:
            await adapter.aclose()

        now = utcnow()
        errors: list[str] = []
        upserted = 0
        for listing in fetched:
            try:
                await self.listings.upsert(
                    provider,
                    listing.marketplace_sku,
                    {
                        "external_listing_id": listing.external_listing_id,
                        "title": listing.title,
                        "price": listing.price,
                        "currency": listing.currency,
                        "stock": listing.stock,
                        "status": _map_status(listing.status),
                        "last_synced_at": now,
                        "sync_error": None,
                        "raw": listing.raw,
                    },
                )
                upserted += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{listing.marketplace_sku}: {exc}")
        await self.session.commit()
        log.info(
            "marketplace.sync_listings",
            provider=provider,
            fetched=len(fetched),
            upserted=upserted,
        )
        return SyncResult(
            provider=provider,
            operation="listings",
            mode=settings.MARKETPLACE_MODE,
            fetched=len(fetched),
            upserted=upserted,
            errors=errors,
        )

    async def fetch_orders(
        self, provider: str, *, limit: int = 50, page: int = 1
    ) -> list[dict]:
        adapter = await self._adapter(provider)
        try:
            orders = await adapter.fetch_orders(limit=limit, page=page)
        except IntegrationError as exc:
            _raise_http_from_integration(provider, exc)
        finally:
            await adapter.aclose()
        return [
            {
                "external_order_id": o.external_order_id,
                "marketplace_sku": o.marketplace_sku,
                "quantity": o.quantity,
                "total": str(o.total) if o.total is not None else None,
                "currency": o.currency,
                "status": o.status,
            }
            for o in orders
        ]

    # ---- stored reads -----------------------------------------------------
    async def list_prices(
        self, provider: str | None = None, *, limit: int = 50, offset: int = 0
    ):
        if provider is not None:
            return await self.prices.list_by_provider(
                provider, limit=limit, offset=offset
            )
        return await self.prices.list(limit=limit, offset=offset)

    async def list_listings(
        self, provider: str | None = None, *, limit: int = 50, offset: int = 0
    ):
        return await self.listings.list_by_provider(
            provider, limit=limit, offset=offset
        )
