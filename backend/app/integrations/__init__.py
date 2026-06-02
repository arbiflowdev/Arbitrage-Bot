"""Marketplace integration adapters and the unified abstraction layer.

Public surface:
    * :func:`build_adapter` / :data:`SUPPORTED_PROVIDERS` — registry
    * :class:`MarketplaceAdapter` + normalized dataclasses — the interface
    * integration exceptions — provider-agnostic error types
"""

from app.integrations.base import (
    MarketplaceAdapter,
    NormalizedListing,
    NormalizedOrder,
    NormalizedPrice,
    NormalizedProduct,
    ParsedWebhook,
    ProviderCredentials,
    to_decimal,
)
from app.integrations.exceptions import (
    CredentialsNotConfigured,
    IntegrationError,
    ProviderAPIError,
    ProviderUnavailable,
    RateLimitExceeded,
    WebhookVerificationError,
)
from app.integrations.registry import (
    SUPPORTED_PROVIDERS,
    build_adapter,
    is_supported,
    resolve_credentials,
)

__all__ = [
    "MarketplaceAdapter",
    "NormalizedListing",
    "NormalizedOrder",
    "NormalizedPrice",
    "NormalizedProduct",
    "ParsedWebhook",
    "ProviderCredentials",
    "to_decimal",
    "CredentialsNotConfigured",
    "IntegrationError",
    "ProviderAPIError",
    "ProviderUnavailable",
    "RateLimitExceeded",
    "WebhookVerificationError",
    "SUPPORTED_PROVIDERS",
    "build_adapter",
    "is_supported",
    "resolve_credentials",
]
