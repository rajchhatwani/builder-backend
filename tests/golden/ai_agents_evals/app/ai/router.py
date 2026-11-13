"""AI gateway routes (generated, pack ai.gateway). Every route needs sign-in; roles come from the spec
(packs.ai.gateway.roles: call_roles, read_roles, manage_roles). Rules: app/ai/service.py."""

import typing as _t
import uuid as _uuid

import fastapi as _fa
from fastapi import Depends, Query, Response

from app.ai import config as _config
from app.ai import schemas as _s
from app.ai import service as _svc
from app.auth.deps import CurrentUser
from app.auth.models import AuthUser
from app.core.errors import AppError
from app.core.pagination import Page
from app.db import SessionDep

router = _fa.APIRouter(prefix="/ai", tags=["ai"])


def _allow(user: AuthUser, *groups: tuple[str, ...]) -> AuthUser:
    """Allowed when any group is empty (= any signed-in user) or the caller has a role of any group."""
    if all(groups) and not any(_svc.has_role(user, g) for g in groups):
        raise AppError("forbidden", "you do not have permission to do that", 403)
    return user


async def _caller(user: CurrentUser) -> AuthUser:
    return _allow(user, _config.CALL_ROLES, _config.MANAGE_ROLES)


async def _reader(user: CurrentUser) -> AuthUser:
    return _allow(user, _config.READ_ROLES, _config.MANAGE_ROLES)


Caller = _t.Annotated[AuthUser, Depends(_caller)]
Reader = _t.Annotated[AuthUser, Depends(_reader)]
Limit = _t.Annotated[int, Query(ge=1, le=200)]
Offset = _t.Annotated[int, Query(ge=0)]


@router.post("/complete", response_model=_s.CompleteOut)
async def complete(body: _s.CompleteIn, response: Response, session: SessionDep, user: Caller) -> _s.CompleteOut:
    out = await _svc.complete(session, user, body)
    if out.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return out


@router.get("/calls", response_model=Page[_s.CallOut])
async def list_calls(
    session: SessionDep,
    user: Reader,
    limit: Limit = 50,
    offset: Offset = 0,
    stage: _t.Annotated[str | None, Query(max_length=40)] = None,
    status: _t.Annotated[_t.Literal["reserved", "ok", "error"] | None, Query()] = None,
    caller_id: _uuid.UUID | None = None,
) -> Page[_s.CallOut]:
    items, total = await _svc.list_calls(session, user, limit, offset, stage, status, caller_id)
    return Page[_s.CallOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/usage", response_model=_s.UsageOut)
async def usage(session: SessionDep, user: Reader) -> _s.UsageOut:
    return await _svc.usage(session, user)
