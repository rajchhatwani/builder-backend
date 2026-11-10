"""Per-row custom fields (CP4F2-B), applied as typed ops so history/undo/planner see them.

GET    /projects/{id}/entities/{entity}/custom-fields                       list (viewer)
POST   /projects/{id}/entities/{entity}/custom-fields                       define (editor)
PATCH  /projects/{id}/entities/{entity}/custom-fields/{name}                update (editor)
DELETE /projects/{id}/entities/{entity}/custom-fields/{name}                remove (editor)
POST   /projects/{id}/entities/{entity}/custom-fields/{name}/promote-check  dry run, writes nothing (editor)
POST   /projects/{id}/entities/{entity}/custom-fields/{name}/promote        promote to a real column (editor)
"""

import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.spec_ops import request_actor
from app.db import get_session
from app.schemas.custom_fields import (
    CustomFieldDef,
    CustomFieldList,
    CustomFieldPatch,
    PromoteCheckBody,
    PromoteCheckResult,
    PromoteResult,
)
from app.services.custom_field_service import CustomFieldService

router = APIRouter(prefix="/projects/{project_id}/entities/{entity}/custom-fields", tags=["custom-fields"])


@router.get("", response_model=CustomFieldList)
async def list_custom_fields(
    project_id: uuid.UUID, entity: str, db: AsyncSession = Depends(get_session)
) -> CustomFieldList:
    return await CustomFieldService(db).list_defs(project_id, entity)


@router.post("", response_model=CustomFieldDef, status_code=status.HTTP_201_CREATED)
async def define_custom_field(
    project_id: uuid.UUID,
    entity: str,
    body: CustomFieldDef,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> CustomFieldDef:
    return await CustomFieldService(db).define(project_id, entity, body, request_actor(request))


@router.patch("/{name}", response_model=CustomFieldDef)
async def update_custom_field(
    project_id: uuid.UUID,
    entity: str,
    name: str,
    body: CustomFieldPatch,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> CustomFieldDef:
    return await CustomFieldService(db).update(
        project_id, entity, name, body.model_dump(exclude_unset=True), request_actor(request)
    )


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_custom_field(
    project_id: uuid.UUID,
    entity: str,
    name: str,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> None:
    await CustomFieldService(db).remove(project_id, entity, name, request_actor(request))


@router.post("/{name}/promote-check", response_model=PromoteCheckResult)
async def promote_check(
    project_id: uuid.UUID,
    entity: str,
    name: str,
    body: PromoteCheckBody | None = None,
    db: AsyncSession = Depends(get_session),
) -> PromoteCheckResult:
    samples = body.samples if body is not None else None
    return await CustomFieldService(db).promote_check(project_id, entity, name, samples)


@router.post("/{name}/promote", response_model=PromoteResult)
async def promote_custom_field(
    project_id: uuid.UUID,
    entity: str,
    name: str,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> PromoteResult:
    return await CustomFieldService(db).promote(project_id, entity, name, request_actor(request))
