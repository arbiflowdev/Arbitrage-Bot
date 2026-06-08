"""Domain errors for the fulfillment pipeline."""

from __future__ import annotations


class FulfillmentError(Exception):
    """Base class for fulfillment-domain failures."""


class InsufficientFunds(FulfillmentError):  # noqa: N818 - descriptive name
    """A wallet debit was rejected because the balance is too low."""


class SourcingUnavailable(FulfillmentError):  # noqa: N818 - descriptive name
    """No source marketplace could supply the product for a JIT purchase."""


class DeliveryFailed(FulfillmentError):  # noqa: N818 - descriptive name
    """The marketplace rejected or failed the delivery of a code."""
