"""Marketplace webhook endpoints.

``POST /webhooks/{provider}`` is public (marketplaces call it) and secured by
per-provider signature verification rather than JWT. ``GET /webhook-events`` is
admin-only and exposes the stored audit trail.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request, status

from app.core.dependencies import CurrentAdmin, SessionDep
from app.schemas.marketplace import WebhookAck, WebhookEventRead
from app.services.webhook_service import WebhookService

router = APIRouter(tags=["webhooks"])


@router.post(
    "/webhooks/{provider}",
    response_model=WebhookAck,
    summary="Receive a marketplace webhook (signature-verified)",
)
async def receive_webhook(
    provider: str, request: Request, session: SessionDep
) -> WebhookAck:
    body = await request.body()
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook body is not valid JSON.",
        ) from exc
    if not isinstance(payload, dict):
        payload = {"data": payload}

    headers = {k.lower(): v for k, v in request.headers.items()}
    return await WebhookService(session).handle(provider, headers, body, payload)


@router.get(
    "/webhook-events",
    response_model=list[WebhookEventRead],
    summary="List received webhook events (admin only)",
)
async def list_webhook_events(
    _: CurrentAdmin,
    session: SessionDep,
    provider: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[WebhookEventRead]:
    events = await WebhookService(session).list_events(
        provider, limit=limit, offset=offset
    )
    return [WebhookEventRead.model_validate(e) for e in events]
