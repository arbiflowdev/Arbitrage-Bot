"""Exceptions raised by marketplace adapters.

These are deliberately provider-agnostic so the service layer and API can
handle integration failures uniformly regardless of which marketplace failed.
"""

from __future__ import annotations


class IntegrationError(Exception):
    """Base class for all marketplace integration failures."""


class CredentialsNotConfigured(IntegrationError):  # noqa: N818 - descriptive name
    """No active API credential exists for the provider (adapter is dormant)."""


class ProviderUnavailable(IntegrationError):  # noqa: N818 - descriptive name
    """The provider could not be reached (network/DNS/timeout after retries)."""


class RateLimitExceeded(IntegrationError):  # noqa: N818 - descriptive name
    """A rate limit was hit (locally enforced or returned by the provider)."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ProviderAPIError(IntegrationError):
    """The provider returned an error response (non-2xx after retries)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: object | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class WebhookVerificationError(IntegrationError):
    """A webhook payload failed signature verification."""
