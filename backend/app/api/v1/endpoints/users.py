"""User management endpoints (admin only).

There is no public sign-up: this platform is operated by admins, so operator
accounts are provisioned here by an existing admin (or via the
``BOOTSTRAP_ADMIN_*`` env vars on first boot). Admins can create accounts,
promote/demote roles, and activate/deactivate users.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, status

from app.core.dependencies import CurrentAdmin, SessionDep
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserRead, UserUpdate

router = APIRouter(tags=["users"])


@router.get("/users", response_model=list[UserRead], summary="List users")
async def list_users(
    _: CurrentAdmin,
    session: SessionDep,
    limit: int = 100,
    offset: int = 0,
) -> list[UserRead]:
    rows = await UserRepository(session).list(limit=limit, offset=offset)
    return [UserRead.model_validate(r) for r in rows]


@router.post(
    "/users",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an operator account (admin or user)",
)
async def create_user(
    _: CurrentAdmin,
    session: SessionDep,
    payload: Annotated[UserCreate, Body()],
) -> UserRead:
    repo = UserRepository(session)
    email = payload.email.lower()
    if await repo.email_exists(email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )
    user = User(
        email=email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        is_active=True,
    )
    await repo.add(user)
    await session.commit()
    await session.refresh(user)
    return UserRead.model_validate(user)


@router.patch(
    "/users/{user_id}",
    response_model=UserRead,
    summary="Update a user's role or active state",
)
async def update_user(
    current: CurrentAdmin,
    session: SessionDep,
    user_id: int,
    payload: Annotated[UserUpdate, Body()],
) -> UserRead:
    repo = UserRepository(session)
    user = await repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    # Guard against an admin locking themselves out of the platform.
    if user.id == current.id and (
        payload.is_active is False
        or (payload.role is not None and payload.role != UserRole.ADMIN)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot demote or deactivate your own account.",
        )
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    await session.commit()
    await session.refresh(user)
    return UserRead.model_validate(user)
