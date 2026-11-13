"""Knowledge library routes (generated, pack ai.knowledge). Roles come from the spec (packs.ai.knowledge); what a caller
SEES of each source is decided by the source itself (allowed_roles / owner_only). Rules: app/ai/knowledge_service.py."""

import typing as _t
import uuid as _uuid

import fastapi as _fa
from fastapi import Depends, Query, Response

from app.ai import knowledge_config as _config
from app.ai import knowledge_schemas as _s
from app.ai import knowledge_service as _svc
from app.ai import service as _gateway
from app.auth.deps import CurrentUser
from app.auth.models import AuthUser
from app.core.errors import AppError
from app.core.pagination import Page
from app.db import SessionDep

router = _fa.APIRouter(prefix="/ai/knowledge", tags=["ai-knowledge"])


def _allow(user: AuthUser, *groups: tuple[str, ...]) -> AuthUser:
    """Allowed when any group is empty (= any signed-in user) or the caller has a role of any group."""
    if all(groups) and not any(_gateway.has_role(user, g) for g in groups):
        raise AppError("forbidden", "you do not have permission to do that", 403)
    return user


async def _manager(user: CurrentUser) -> AuthUser:
    return _allow(user, _config.MANAGE_ROLES)


async def _reader(user: CurrentUser) -> AuthUser:
    return _allow(user, _config.READ_ROLES, _config.MANAGE_ROLES)


Manager = _t.Annotated[AuthUser, Depends(_manager)]
Reader = _t.Annotated[AuthUser, Depends(_reader)]
Limit = _t.Annotated[int, Query(ge=1, le=200)]
Offset = _t.Annotated[int, Query(ge=0)]


@router.post("/sources", response_model=_s.SourceOut, status_code=201)
async def create_source(body: _s.SourceIn, session: SessionDep, user: Manager) -> _s.SourceOut:
    return await _svc.create_source(session, user, body)


@router.get("/sources", response_model=Page[_s.SourceOut])
async def list_sources(session: SessionDep, user: Reader, limit: Limit = 50, offset: Offset = 0) -> Page[_s.SourceOut]:
    items, total = await _svc.list_sources(session, user, limit, offset)
    return Page[_s.SourceOut](items=items, total=total, limit=limit, offset=offset)


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: _uuid.UUID, session: SessionDep, user: Reader) -> Response:
    await _svc.delete_source(session, user, source_id)
    return Response(status_code=204)


@router.post("/search", response_model=_s.SearchOut)
async def search(body: _s.SearchIn, session: SessionDep, user: Reader) -> _s.SearchOut:
    return _s.SearchOut(hits=await _svc.search(session, user, body.query, body.limit))


@router.post("/ask", response_model=_s.AskOut)
async def ask(body: _s.AskIn, session: SessionDep, user: Reader) -> _s.AskOut:
    return await _svc.ask(session, user, body)
