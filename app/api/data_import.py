"""Data import (B4-1, C16): CSV upload with mapping preview, review queue, idempotent commit.

POST /projects/{project_id}/imports                      multipart file + entity (+ mapping JSON) (editor)
GET  /projects/{project_id}/imports                      batches (viewer)
GET  /projects/{project_id}/imports/records?entity=      committed records (viewer)
GET  /projects/{project_id}/imports/records/export.csv?entity=  CSV export, <=10000 rows (viewer)
GET  /projects/{project_id}/imports/{batch_id}           preview again (viewer)
PUT  /projects/{project_id}/imports/{batch_id}/mapping   re-validate the whole batch (editor)
GET  /projects/{project_id}/imports/{batch_id}/rows      review queue, ?status= (viewer)
PUT  /projects/{project_id}/imports/{batch_id}/rows/{row_id}  fix one row (editor)
POST /projects/{project_id}/imports/{batch_id}/commit    (editor)
POST /projects/{project_id}/imports/{batch_id}/cancel    (editor)

Records land in the platform's own store; delivery into a generated app is a later work package.
"""

import uuid

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.security import current_principal, request_info
from app.core import data_import as di
from app.db import get_session
from app.exceptions import AppError
from app.models.enums import AuditResult
from app.models.project import Project
from app.schemas.data_import import (
    BatchPage,
    BatchRead,
    CommitResult,
    ImportPreview,
    MappingBody,
    RecordPage,
    RowFix,
    RowPage,
    RowRead,
)
from app.services import audit_service
from app.services.access_service import Principal
from app.services.import_service import ImportService


def _role(request: Request) -> str | None:
    """The caller's project role (set by the access guard); None fails closed in the service."""
    role = getattr(request.state, "member_role", None)
    return str(role.value) if role is not None else None


router = APIRouter(prefix="/projects/{project_id}/imports", tags=["import"])


@router.post("", response_model=ImportPreview, status_code=201)
async def upload(
    project_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    entity: str = Form(..., min_length=1, max_length=120),
    mapping: str | None = Form(default=None, max_length=20_000),
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> ImportPreview:
    data = await file.read(di.MAX_BYTES + 1)  # never buffer more than the cap allows
    if len(data) > di.MAX_BYTES:
        raise AppError("import_too_large", f"the file is larger than {di.MAX_BYTES} bytes", 413)
    return await ImportService(db).create_preview(
        project_id, principal.user.id, file.filename or "import.csv", data, entity, mapping, _role(request)
    )


@router.get("", response_model=BatchPage)
async def list_imports(
    project_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_session),
) -> BatchPage:
    return await ImportService(db).list_batches(project_id, limit, offset)


@router.get("/records", response_model=RecordPage)
async def list_records(
    project_id: uuid.UUID,
    request: Request,
    entity: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_session),
) -> RecordPage:
    return await ImportService(db).list_records(project_id, entity, limit, offset, _role(request))


@router.get("/records/export.csv", response_class=Response)
async def export_records(
    project_id: uuid.UUID,
    request: Request,
    entity: str = Query(min_length=1, max_length=120),
    db: AsyncSession = Depends(get_session),
) -> Response:
    body, truncated = await ImportService(db).export_csv(project_id, entity, _role(request))
    headers = {
        "Content-Disposition": 'attachment; filename="records.csv"',
        "X-Export-Truncated": "true" if truncated else "false",
    }
    return Response(body, media_type="text/csv; charset=utf-8", headers=headers)


@router.get("/{batch_id}", response_model=ImportPreview)
async def get_import(
    project_id: uuid.UUID,
    batch_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> ImportPreview:
    return await ImportService(db).get_preview(project_id, batch_id, _role(request))


@router.put("/{batch_id}/mapping", response_model=ImportPreview)
async def put_mapping(
    project_id: uuid.UUID,
    batch_id: uuid.UUID,
    body: MappingBody,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> ImportPreview:
    return await ImportService(db).set_mapping(project_id, batch_id, body.mapping, _role(request))


@router.get("/{batch_id}/rows", response_model=RowPage)
async def list_rows(
    project_id: uuid.UUID,
    batch_id: uuid.UUID,
    request: Request,
    status: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_session),
) -> RowPage:
    return await ImportService(db).list_rows(project_id, batch_id, status, limit, offset, _role(request))


@router.put("/{batch_id}/rows/{row_id}", response_model=RowRead)
async def fix_row(
    project_id: uuid.UUID,
    batch_id: uuid.UUID,
    row_id: uuid.UUID,
    body: RowFix,
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> RowRead:
    return await ImportService(db).fix_row(project_id, batch_id, row_id, body.values, _role(request))


@router.post("/{batch_id}/commit", response_model=CommitResult)
async def commit(
    project_id: uuid.UUID,
    batch_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> CommitResult:
    result, fresh = await ImportService(db).commit(project_id, batch_id)
    if fresh:
        project = await db.get(Project, project_id)
        info = request_info(request)
        await audit_service.record(
            db,
            action="import.commit",
            result=AuditResult.ok,
            actor_id=principal.user.id,
            actor_email=principal.user.email,
            via=principal.via,
            target_type="import_batch",
            target_id=batch_id,
            project_id=project_id,
            organization_id=project.organization_id if project else None,
            client_ip=info.client_ip,
            request_id=info.request_id,
            detail={"created": result.created, "duplicate": result.duplicate, "rejected": result.rejected},
        )
        await db.commit()
    return result


@router.post("/{batch_id}/cancel", response_model=BatchRead)
async def cancel(
    project_id: uuid.UUID, batch_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> BatchRead:
    return await ImportService(db).cancel(project_id, batch_id)
