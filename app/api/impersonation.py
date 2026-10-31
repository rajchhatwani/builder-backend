"""The customer-surface side of "view as" (§4.5): what the banner shows, the operator's
"allow writes" switch, and ending the session. Only a "view as" token has anything to show here;
every other caller gets 404. The operator's side lives in app/api/admin.py."""

from dataclasses import replace

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.security import current_principal, request_info
from app.config import Settings, get_settings
from app.db import get_session
from app.exceptions import AppError
from app.schemas.account import ImpersonationState, ImpersonationWrites
from app.services.access_service import Principal
from app.services.impersonation_service import ImpersonationService

router = APIRouter(prefix="/account/impersonation", tags=["impersonation"])


def _viewing(principal: Principal) -> None:
    if principal.impersonation is None:
        raise AppError(code="not_found", message="not viewing as anyone", status_code=404)


def _state(principal: Principal) -> ImpersonationState:
    info = principal.impersonation
    assert info is not None
    return ImpersonationState(
        session_id=info.session_id,
        operator_email=info.operator_email,
        user_email=principal.user.email,
        organization_id=info.organization_id,
        organization_slug=info.organization_slug,
        organization_name=info.organization_name,
        expires_at=info.expires_at,
        writes_allowed=info.writes_allowed(),
        writes_until=info.writes_until,
    )


@router.get("", response_model=ImpersonationState)
async def state(principal: Principal = Depends(current_principal)) -> ImpersonationState:
    _viewing(principal)
    return _state(principal)


@router.post("/writes", response_model=ImpersonationState)
async def set_writes(
    body: ImpersonationWrites,
    request: Request,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ImpersonationState:
    """Switch writes on for a few minutes (or off again). Audited both ways."""
    _viewing(principal)
    row = await ImpersonationService(db, settings).set_writes(
        principal, body.enabled, request_info(request)
    )
    info = principal.impersonation
    assert info is not None
    refreshed = replace(principal, impersonation=replace(info, writes_until=row.writes_until))
    return _state(refreshed)


@router.post("/end", status_code=status.HTTP_204_NO_CONTENT)
async def end(
    request: Request,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    _viewing(principal)
    assert principal.impersonation is not None
    await ImpersonationService(db, settings).end(
        principal.impersonation.session_id,
        by=principal,
        why="ended_by_viewer",
        info=request_info(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
