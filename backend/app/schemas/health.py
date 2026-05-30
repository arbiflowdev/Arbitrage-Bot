"""Health-check schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Status = Literal["ok", "degraded", "down"]


class ComponentHealth(BaseModel):
    status: Status
    latency_ms: float | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: Status
    app: str
    version: str
    environment: str
    components: dict[str, ComponentHealth]
