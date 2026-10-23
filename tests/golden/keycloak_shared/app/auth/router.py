"""HTTP routes for authentication with Keycloak (generated).

Signing in, registering, password reset and token refresh all happen in Keycloak, so this
project only offers the caller's own profile."""
import datetime as _dt
import uuid as _uuid

import fastapi as _fa
import pydantic as _pd

from app.auth import service
from app.auth.deps import CurrentUser
from app.db import SessionDep

router = _fa.APIRouter(prefix="/auth", tags=["auth"])


class UserRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    email: str | None
    name: str | None
    roles: list[str]
    created_at: _dt.datetime


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.delete("/me", status_code=204)
async def delete_me(user: CurrentUser, session: SessionDep) -> None:
    """Erases the caller's profile here. Their Keycloak account is deleted in Keycloak."""
    await service.delete_account(session, user)
