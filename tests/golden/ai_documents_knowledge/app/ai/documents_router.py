"""Document AI routes (generated, pack ai.documents). Roles come from the spec (packs.ai.documents). Rules: app/ai/documents_service.py."""

import typing as _t
import uuid as _uuid

import fastapi as _fa
from fastapi import Depends, Query, Response

from app.ai import documents_config as _config
from app.ai import documents_schemas as _s
from app.ai import documents_service as _svc
from app.ai import service as _gateway
from app.auth.deps import CurrentUser
from app.auth.models import AuthUser
from app.core.errors import AppError
from app.core.pagination import Page
from app.db import SessionDep

router = _fa.APIRouter(prefix="/ai/documents", tags=["ai-documents"])


def _allow(user: AuthUser, *groups: tuple[str, ...]) -> AuthUser:
    """Allowed when any group is empty (= any signed-in user) or the caller has a role of any group."""
    if all(groups) and not any(_gateway.has_role(user, g) for g in groups):
        raise AppError("forbidden", "you do not have permission to do that", 403)
    return user


async def _uploader(user: CurrentUser) -> AuthUser:
    return _allow(user, _config.UPLOAD_ROLES)


async def _reader(user: CurrentUser) -> AuthUser:
    return _allow(user, _config.READ_ROLES, _config.REVIEW_ROLES, _config.UPLOAD_ROLES)


async def _reviewer(user: CurrentUser) -> AuthUser:
    return _allow(user, _config.REVIEW_ROLES)


Uploader = _t.Annotated[AuthUser, Depends(_uploader)]
Reader = _t.Annotated[AuthUser, Depends(_reader)]
Reviewer = _t.Annotated[AuthUser, Depends(_reviewer)]
Limit = _t.Annotated[int, Query(ge=1, le=200)]
Offset = _t.Annotated[int, Query(ge=0)]
FieldName = _t.Annotated[str, _fa.Path(max_length=40)]


@router.post("", response_model=_s.DocumentOut, status_code=201)
async def create_document(body: _s.DocumentIn, response: Response, session: SessionDep, user: Uploader) -> _s.DocumentOut:
    out, replayed = await _svc.create(session, user, body)
    if replayed:
        response.status_code = 200
        response.headers["Idempotent-Replayed"] = "true"
    return out


@router.get("", response_model=Page[_s.DocumentOut])
async def list_documents(
    session: SessionDep,
    user: Reader,
    limit: Limit = 50,
    offset: Offset = 0,
    status: _t.Annotated[_s.DocumentStatus | None, Query()] = None,
    kind: _t.Annotated[str | None, Query(max_length=40)] = None,
) -> Page[_s.DocumentOut]:
    items, total = await _svc.list_documents(session, user, limit, offset, status, kind)
    return Page[_s.DocumentOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/{document_id}", response_model=_s.DocumentOut)
async def get_document(document_id: _uuid.UUID, session: SessionDep, user: Reader) -> _s.DocumentOut:
    return await _svc.get(session, user, document_id)


@router.post("/{document_id}/fields/{name}/correct", response_model=_s.DocumentOut)
async def correct_field(document_id: _uuid.UUID, name: FieldName, body: _s.CorrectIn, session: SessionDep, user: Reviewer) -> _s.DocumentOut:
    return await _svc.correct(session, user, document_id, name, body.value)


@router.post("/{document_id}/approve", response_model=_s.DocumentOut)
async def approve_document(
    document_id: _uuid.UUID, session: SessionDep, user: Reviewer, body: _s.ApproveIn | None = None
) -> _s.DocumentOut:
    return await _svc.approve(session, user, document_id, body.acknowledge if body is not None else None)


@router.post("/{document_id}/reject", response_model=_s.DocumentOut)
async def reject_document(
    document_id: _uuid.UUID, session: SessionDep, user: Reviewer, body: _s.RejectIn | None = None
) -> _s.DocumentOut:
    return await _svc.reject(session, user, document_id, body.reason if body is not None else None)
