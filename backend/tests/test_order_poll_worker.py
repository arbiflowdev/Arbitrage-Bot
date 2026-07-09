"""OrderPollWorker: one marketplace failing must not abort polling the others.

Regression test for the production incident where Kinguin (polled first) returned
HTTP 401 on an expired key, the exception propagated out of the provider loop, and
the whole poll cycle aborted — so the G2G/Eneba safety-net poll never ran. Each
provider is now isolated: a failure is logged and the loop continues.
"""

from __future__ import annotations

import pytest

from app.integrations import SUPPORTED_PROVIDERS
from app.workers.order_poll_worker import OrderPollWorker


@pytest.mark.asyncio
async def test_provider_failure_does_not_abort_remaining_providers(monkeypatch) -> None:
    polled: list[str] = []

    async def fake_poll(self, provider, intake) -> int:
        polled.append(provider)
        if provider == "kinguin":
            raise RuntimeError("'kinguin' API error: HTTP 401.")
        return 1

    monkeypatch.setattr(OrderPollWorker, "_poll_provider", fake_poll)

    ingested = await OrderPollWorker()._poll_all(intake=None)

    # Every provider was attempted, even though the first one raised.
    assert set(polled) == set(SUPPORTED_PROVIDERS)
    # The surviving providers' ingests still counted despite the failure.
    assert ingested == len(SUPPORTED_PROVIDERS) - 1
