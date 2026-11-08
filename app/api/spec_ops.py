import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination, pagination
from app.db import get_session
from app.exceptions import AppError
from app.schemas.common import Page
from app.schemas.spec_ops import SpecOpApply, SpecOpRead, SpecRestore
from app.services.access_service import Principal
from app.services.ops.scope import Actor
from app.services.ops.service import OpsService, to_read

router = APIRouter(prefix="/projects/{project_id}/spec", tags=["spec-ops"])


def request_actor(request: Request) -> Actor:
    """The person behind this request. The guard authenticated it and put the principal on the
    request; a request without one never reaches these routes."""
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, Principal):
        raise AppError(code="unauthenticated", message="sign in to continue", status_code=401)
    return Actor("user", principal.user.id)


@router.get("/ops", response_model=Page[SpecOpRead])
async def list_ops(
    project_id: uuid.UUID,
    page: Pagination = Depends(pagination),
    session: AsyncSession = Depends(get_session),
) -> Page[SpecOpRead]:
    items, total = await OpsService(session).list_ops(project_id, page.limit, page.offset)
    return Page[SpecOpRead](items=items, total=total, limit=page.limit, offset=page.offset)


@router.post("/ops", response_model=SpecOpRead, status_code=status.HTTP_201_CREATED)
async def apply_op(
    project_id: uuid.UUID,
    body: SpecOpApply,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SpecOpRead:
    applied = await OpsService(session).apply_op(
        project_id, body.op_type, body.payload, request_actor(request)
    )
    return to_read(applied.op)


@router.post("/undo", response_model=SpecOpRead)
async def undo(
    project_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_session)
) -> SpecOpRead:
    return to_read((await OpsService(session).undo(project_id, request_actor(request))).op)


@router.post("/redo", response_model=SpecOpRead)
async def redo(
    project_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_session)
) -> SpecOpRead:
    return to_read((await OpsService(session).redo(project_id, request_actor(request))).op)


@router.post("/restore", response_model=SpecOpRead)
async def restore(
    project_id: uuid.UUID,
    body: SpecRestore,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SpecOpRead:
    applied = await OpsService(session).restore(project_id, body.to_seq, request_actor(request))
    return to_read(applied.op)
