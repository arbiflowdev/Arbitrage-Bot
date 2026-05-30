"""Authentication endpoints: /login, /register, /me."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.core.dependencies import CurrentUser, SessionDep
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
)
from app.schemas.user import UserRead
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(payload: RegisterRequest, session: SessionDep) -> RegisterResponse:
    service = AuthService(session)
    user = await service.register(payload)
    token = service.issue_token(user)
    return RegisterResponse(user=UserRead.model_validate(user), token=token)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Exchange email + password for an access token",
)
async def login(payload: LoginRequest, session: SessionDep) -> TokenResponse:
    service = AuthService(session)
    user = await service.authenticate(payload)
    return service.issue_token(user)


@router.get(
    "/me",
    response_model=UserRead,
    summary="Get the currently-authenticated user",
)
async def me(current_user: CurrentUser) -> UserRead:
    return UserRead.model_validate(current_user)
