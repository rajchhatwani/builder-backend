"""Draft workspaces (B3-4). Editors write (platform_authz default); viewers read.

GET    /projects/{project_id}/workspaces                         list (viewer)
POST   /projects/{project_id}/workspaces                         create (editor)
GET    /projects/{project_id}/workspaces/{ws_id}                 read  (viewer)
POST   /projects/{project_id}/workspaces/{ws_id}/checkpoints     checkpoint (editor)
POST   /projects/{project_id}/workspaces/{ws_id}/rollback        rollback (editor)
DELETE /projects/{project_id}/workspaces/{ws_id}                 discard (editor)
GET    /projects/{project_id}/workspaces/{ws_id}/files           list files (viewer)
GET    /projects/{project_id}/workspaces/{ws_id}/files/content   read a file (viewer)
PUT    /projects/{project_id}/workspaces/{ws_id}/files/content   edit a custom-zone file (editor)
"""

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.security import current_principal, request_info
from app.db import get_session
from app.models.project import Project
from app.schemas.workspace import (
    CheckpointCreate,
    CheckpointRead,
    RollbackRequest,
    WorkspaceCreate,
    WorkspaceRead,
)
from app.schemas.workspace_files import WorkspaceFileEntry, WorkspaceFileRead, WorkspaceFileWrite
from app.services.access_service import Principal
from app.services.workspace_files import WorkspaceFileService
from app.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/projects/{project_id}/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceRead])
async def list_workspaces(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> list[WorkspaceRead]:
    return await WorkspaceService(db).list_workspaces(project_id)


@router.post("", response_model=WorkspaceRead, status_code=201)
async def create_workspace(
    project_id: uuid.UUID,
    body: WorkspaceCreate,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> WorkspaceRead:
    return await WorkspaceService(db).create(project_id, principal.user.id, body.name)


@router.get("/{ws_id}", response_model=WorkspaceRead)
async def get_workspace(
    project_id: uuid.UUID, ws_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> WorkspaceRead:
    return await WorkspaceService(db).read(project_id, ws_id)


@router.post("/{ws_id}/checkpoints", response_model=CheckpointRead, status_code=201)
async def create_checkpoint(
    project_id: uuid.UUID,
    ws_id: uuid.UUID,
    body: CheckpointCreate,
    db: AsyncSession = Depends(get_session),
) -> CheckpointRead:
    return await WorkspaceService(db).checkpoint(project_id, ws_id, body.label)


@router.post("/{ws_id}/rollback", response_model=WorkspaceRead)
async def rollback_workspace(
    project_id: uuid.UUID,
    ws_id: uuid.UUID,
    body: RollbackRequest,
    db: AsyncSession = Depends(get_session),
) -> WorkspaceRead:
    return await WorkspaceService(db).rollback(project_id, ws_id, body.checkpoint_id)


@router.delete("/{ws_id}", response_model=WorkspaceRead)
async def discard_workspace(
    project_id: uuid.UUID, ws_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> WorkspaceRead:
    return await WorkspaceService(db).discard(project_id, ws_id)


@router.get("/{ws_id}/files", response_model=list[WorkspaceFileEntry])
async def list_files(
    project_id: uuid.UUID, ws_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> list[WorkspaceFileEntry]:
    return await WorkspaceFileService(db).list_files(project_id, ws_id)


@router.get("/{ws_id}/files/content", response_model=WorkspaceFileRead)
async def read_file(
    project_id: uuid.UUID,
    ws_id: uuid.UUID,
    path: str = Query(min_length=1, max_length=500),
    db: AsyncSession = Depends(get_session),
) -> WorkspaceFileRead:
    return await WorkspaceFileService(db).read(project_id, ws_id, path)


@router.put("/{ws_id}/files/content", response_model=WorkspaceFileRead)
async def write_file(
    project_id: uuid.UUID,
    ws_id: uuid.UUID,
    body: WorkspaceFileWrite,
    request: Request,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> WorkspaceFileRead:
    project = await db.get(Project, project_id)
    info = request_info(request)
    return await WorkspaceFileService(db).write(
        project_id,
        ws_id,
        body.path,
        body.content,
        body.expected_sha256,
        actor_id=principal.user.id,
        actor_email=principal.user.email,
        via=principal.via,
        organization_id=project.organization_id if project else None,
        client_ip=info.client_ip,
        request_id=info.request_id,
    )
