"""Webhook service — verify, de-duplicate, persist, and process inbound events.

Every webhook is recorded in ``webhook_events`` before processing. Signature
verification gates processing, and ``(provider, external_id)`` gives
idempotency so provider replays are not handled twice.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.integrations import (
    SUPPORTED_PROVIDERS,
    build_adapter,
    is_supported,
    resolve_credentials,
)
from app.models.webhook_event import WebhookEvent, WebhookEventStatus
from app.repositories.webhook_event_repository import WebhookEventRepository
from app.schemas.marketplace import WebhookAck
from app.utils.datetime import utcnow

log = get_logger(__name__)


class WebhookService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = WebhookEventRepository(session)

    async def handle(
        self,
        provider: str,
        headers: dict[str, str],
        body: bytes,
        payload: dict[str, Any],
    ) -> WebhookAck:
        if not is_supported(provider):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"Unknown provider '{provider}'. Supported: "
                    f"{', '.join(SUPPORTED_PROVIDERS)}."
                ),
            )

        creds = resolve_credentials(provider)
        adapter = build_adapter(provider, creds)
        try:
            signature_valid = adapter.verify_webhook(headers, body)
            parsed = adapter.parse_webhook(headers, payload)
        finally:
            await adapter.aclose()

        # Idempotency: short-circuit a replay we have already stored.
        if parsed.external_id:
            existing = await self.repo.get_by_external_id(
                provider, parsed.external_id
            )
            if existing is not None:
                log.info(
                    "webhook.duplicate",
                    provider=provider,
                    external_id=parsed.external_id,
                )
                return WebhookAck(
                    received=True,
                    status=existing.status.value,
                    event_id=existing.id,
                    detail="Duplicate event ignored.",
                )

        event = WebhookEvent(
            provider=provider,
            event_type=parsed.event_type,
            external_id=parsed.external_id,
            signature_valid=signature_valid,
            status=WebhookEventStatus.RECEIVED,
            payload=payload,
            headers=dict(headers),
        )
        await self.repo.add(event)
        await self.session.commit()
        await self.session.refresh(event)

        # Reject (but keep a record of) events that fail verification.
        if not signature_valid:
            event.status = WebhookEventStatus.IGNORED
            event.error = "Signature verification failed."
            await self.session.commit()
            log.warning("webhook.invalid_signature", provider=provider, event_id=event.id)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid webhook signature.",
            )

        # Process. Downstream consumers (repricing, fulfilment) arrive in later
        # milestones; for now we record successful receipt.
        try:
            self._process(event)
            event.status = WebhookEventStatus.PROCESSED
            event.processed_at = utcnow()
        except Exception as exc:  # noqa: BLE001 — never crash the webhook endpoint
            event.status = WebhookEventStatus.FAILED
            event.error = str(exc)[:1024]
            log.warning("webhook.process_failed", provider=provider, error=str(exc))
        await self.session.commit()

        return WebhookAck(
            received=True,
            status=event.status.value,
            event_id=event.id,
            detail=None,
        )

    def _process(self, event: WebhookEvent) -> None:
        """Hook for downstream handling. Extended in later milestones."""
        log.info(
            "webhook.processed",
            provider=event.provider,
            event_type=event.event_type,
            event_id=event.id,
        )

    async def list_events(
        self, provider: str | None = None, *, limit: int = 50, offset: int = 0
    ) -> list[WebhookEvent]:
        return await self.repo.list_events(provider, limit=limit, offset=offset)
