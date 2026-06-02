"""Unified marketplace adapter interface + normalized data types.

Every provider (Kinguin, G2G, ...) implements :class:`MarketplaceAdapter`,
translating that provider's API shape into the normalized dataclasses below.
The rest of the application only ever deals with these normalized types, never
with provider-specific payloads — that is the "unified abstraction layer".
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from app.integrations.exceptions import CredentialsNotConfigured

if TYPE_CHECKING:
    from app.integrations.http import MarketplaceHTTPClient


def to_decimal(value: Any) -> Decimal | None:
    """Best-effort conversion of a provider price field to ``Decimal``.

    Accepts ints, floats, and numeric strings; returns ``None`` for missing or
    unparseable values so a single bad field never aborts a whole sync.
    """
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Normalized data types
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ProviderCredentials:
    """Decrypted credentials handed to an adapter at construction time."""

    api_key: str | None = None
    api_secret: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NormalizedProduct:
    marketplace_sku: str
    name: str
    price: Decimal | None = None
    currency: str = "EUR"
    available_qty: int | None = None
    region: str | None = None
    platform: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NormalizedPrice:
    marketplace_sku: str
    price: Decimal
    currency: str = "EUR"
    available_qty: int | None = None
    is_available: bool = True
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NormalizedListing:
    marketplace_sku: str
    external_listing_id: str | None = None
    title: str | None = None
    price: Decimal | None = None
    currency: str | None = "EUR"
    stock: int = 0
    status: str = "active"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NormalizedOrder:
    external_order_id: str
    marketplace_sku: str
    quantity: int = 1
    total: Decimal | None = None
    currency: str = "EUR"
    status: str = "unknown"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedWebhook:
    event_type: str
    external_id: str | None = None
    signature_valid: bool = False
    data: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Adapter interface
# ---------------------------------------------------------------------------


class MarketplaceAdapter(abc.ABC):
    """Provider-agnostic marketplace interface.

    Concrete adapters receive optional decrypted ``credentials`` and a shared
    ``http`` client. Live adapters must call :meth:`_require_credentials`
    before any authenticated call so they stay dormant (raising
    ``CredentialsNotConfigured``) until the operator adds keys.
    """

    #: Stable provider identifier, e.g. ``"kinguin"``. Set by subclasses.
    provider: str = "base"

    def __init__(
        self,
        credentials: ProviderCredentials | None = None,
        http: MarketplaceHTTPClient | None = None,
    ) -> None:
        self.credentials = credentials
        self._http = http

    def _require_credentials(self) -> ProviderCredentials:
        if self.credentials is None or not self.credentials.api_key:
            raise CredentialsNotConfigured(
                f"No active API credential configured for provider "
                f"'{self.provider}'. Add one via the credentials API or paste "
                f"keys into .env to enable live calls."
            )
        return self.credentials

    @property
    def http(self) -> MarketplaceHTTPClient:
        if self._http is None:  # pragma: no cover - guarded by factory
            raise RuntimeError(f"HTTP client not configured for '{self.provider}'.")
        return self._http

    async def aclose(self) -> None:
        """Release the underlying HTTP connection pool, if any."""
        if self._http is not None:
            await self._http.aclose()

    # --- read operations ---------------------------------------------------
    @abc.abstractmethod
    async def fetch_products(
        self, *, limit: int = 50, page: int = 1
    ) -> list[NormalizedProduct]:
        """Fetch the provider's product catalogue (paginated)."""

    @abc.abstractmethod
    async def fetch_prices(
        self, skus: list[str] | None = None
    ) -> list[NormalizedPrice]:
        """Fetch current prices, optionally restricted to specific SKUs."""

    @abc.abstractmethod
    async def fetch_listings(self) -> list[NormalizedListing]:
        """Fetch our own listings as the provider currently sees them."""

    @abc.abstractmethod
    async def fetch_orders(
        self, *, limit: int = 50, page: int = 1
    ) -> list[NormalizedOrder]:
        """Fetch recent orders from the provider."""

    # --- write operations --------------------------------------------------
    @abc.abstractmethod
    async def push_listing(self, listing: NormalizedListing) -> NormalizedListing:
        """Create/update a listing (price + stock) on the provider."""

    # --- health & webhooks -------------------------------------------------
    @abc.abstractmethod
    async def health_check(self) -> bool:
        """Return True if credentials are valid and the API is reachable."""

    @abc.abstractmethod
    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        """Return True if a webhook's signature is valid for this provider."""

    @abc.abstractmethod
    def parse_webhook(
        self, headers: dict[str, str], payload: dict[str, Any]
    ) -> ParsedWebhook:
        """Normalize a verified webhook body into a :class:`ParsedWebhook`."""
