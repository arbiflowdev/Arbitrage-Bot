"""Persistent log records.

Structured logs are emitted to stdout for log aggregators, but the SRS
also requires a queryable error/event table — this model backs that.
"""

from __future__ import annotations

import enum

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import JSONB, Base, TimestampedMixin


class LogLevel(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Log(TimestampedMixin, Base):
    __tablename__ = "logs"

    level: Mapped[LogLevel] = mapped_column(
        Enum(LogLevel, name="log_level", native_enum=False, length=16),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    message: Mapped[str] = mapped_column(String(2000), nullable=False)
    context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
