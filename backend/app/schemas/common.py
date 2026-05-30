"""Reusable schema primitives."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    """Base schema for models read from the ORM."""

    model_config = ConfigDict(from_attributes=True)


class Message(BaseModel):
    detail: str


class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
