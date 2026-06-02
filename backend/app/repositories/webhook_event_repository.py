"""Repository for inbound webhook events."""

from __future__ import annotations

from sqlalchemy import select

from app.models.webhook_event import WebhookEvent
from app.repositories.base import BaseRepository


class WebhookEventRepository(BaseRepository[WebhookEvent]):
    model = WebhookEvent

    async def get_by_external_id(
        self, provider: str, external_id: str
    ) -> WebhookEvent | None:
        """Look up an event for idempotency; returns None when external_id is unseen."""
        stmt = select(WebhookEvent).where(
            WebhookEvent.provider == provider,
            WebhookEvent.external_id == external_id,
        )
        return await self.session.scalar(stmt)

    async def list_events(
        self,
        provider: str | None = None,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WebhookEvent]:
        stmt = (
            select(WebhookEvent)
            .order_by(WebhookEvent.id.desc())
            .limit(limit)
            .offset(offset)
        )
        if provider is not None:
            stmt = stmt.where(WebhookEvent.provider == provider)
        result = await self.session.scalars(stmt)
        return list(result.all())
