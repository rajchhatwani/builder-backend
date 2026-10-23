"""HTTP routes for authentication with Keycloak (generated).

Signing in, registering, password reset and token refresh all happen in Keycloak, so this
project only offers the caller's own profile."""

import datetime as dt
import uuid

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.auth import service
from app.auth.deps import CurrentUser
from app.db import SessionDep

router = APIRouter(prefix="/auth", tags=["auth"])


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str | None
    name: str | None
    roles: list[str]
    created_at: dt.datetime


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.delete("/me", status_code=204)
async def delete_me(user: CurrentUser, session: SessionDep) -> None:
    """Erases the caller's profile here. Their Keycloak account is deleted in Keycloak."""
    await service.delete_account(session, user)
