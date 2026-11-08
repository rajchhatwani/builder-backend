"""Dependency policy (B3-9): curated sets, allow-list, gated unknowns.

    GET  /projects/{id}/dependencies                          policy + approved pins   (viewer)
    GET  /projects/{id}/dependencies/requests                 requests                 (viewer)
    POST /projects/{id}/dependencies/requests                 request_dependency       (editor)
    POST /projects/{id}/dependencies/requests/{rid}/approve   approve                  (owner)
    POST /projects/{id}/dependencies/requests/{rid}/deny      deny                     (owner)
    POST /projects/{id}/dependencies/requests/{rid}/revoke    revoke an approval       (owner)
"""

import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.security import current_principal, request_info
from app.db import get_session
from app.models.enums import AuditResult
from app.models.project import Project
from app.schemas.dependency_policy import (
    ApprovedPin,
    DependencyDecision,
    DependencyPolicyRead,
    DependencyRequestRead,
    DependencyRequestWrite,
)
from app.services import audit_service
from app.services.access_service import Principal
from app.services.dependency_policy_service import (
    ALLOW_LIST,
    CURATED_SETS,
    DependencyPolicyService,
)

router = APIRouter(prefix="/projects/{project_id}/dependencies", tags=["dependencies"])


@router.get("", response_model=DependencyPolicyRead)
async def get_policy(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> DependencyPolicyRead:
    svc = DependencyPolicyService(db)
    rows = await svc.list_requests(project_id)
    active = {r.id for r in await svc.approved_pins(project_id)}
    return DependencyPolicyRead(
        curated_sets=CURATED_SETS,
        allow_list=sorted(ALLOW_LIST),
        approved=[
            ApprovedPin(
                package=r.package, version=r.version, hashes=r.hashes, expires_at=r.expires_at
            )
            for r in rows
            if r.id in active
        ],
        pending_requests=sum(1 for r in rows if r.status == "pending"),
    )


@router.get("/requests", response_model=list[DependencyRequestRead])
async def list_requests(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> list[DependencyRequestRead]:
    rows = await DependencyPolicyService(db).list_requests(project_id)
    return [DependencyRequestRead.model_validate(r) for r in rows]


@router.post("/requests", response_model=DependencyRequestRead, status_code=201)
async def request_dependency(
    project_id: uuid.UUID,
    body: DependencyRequestWrite,
    response: Response,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> DependencyRequestRead:
    row, created = await DependencyPolicyService(db).request(
        project_id, body.package, body.version, body.reason, body.hashes, principal.user.id
    )
    await db.commit()
    response.status_code = 201 if created else 200
    return DependencyRequestRead.model_validate(row)


async def _decide(
    approve: bool,
    project_id: uuid.UUID,
    request_id: uuid.UUID,
    body: DependencyDecision,
    request: Request,
    principal: Principal,
    db: AsyncSession,
) -> DependencyRequestRead:
    row = await DependencyPolicyService(db).decide(
        project_id,
        request_id,
        approve,
        principal.user.id,
        body.package,
        body.version,
        body.hashes,
        body.note,
    )
    project = await db.get(Project, project_id)
    info = request_info(request)
    await audit_service.record(
        db,
        action="dependency.approve" if approve else "dependency.deny",
        result=AuditResult.ok,
        actor_id=principal.user.id,
        actor_email=principal.user.email,
        via=principal.via,
        target_type="project",
        target_id=project_id,
        organization_id=project.organization_id if project else None,
        client_ip=info.client_ip,
        request_id=info.request_id,
        detail={"package": row.package, "version": row.version, "hashes": row.hashes},
    )
    await db.commit()
    return DependencyRequestRead.model_validate(row)


@router.post("/requests/{request_id}/approve", response_model=DependencyRequestRead)
async def approve_request(
    project_id: uuid.UUID,
    request_id: uuid.UUID,
    body: DependencyDecision,
    request: Request,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> DependencyRequestRead:
    return await _decide(True, project_id, request_id, body, request, principal, db)


@router.post("/requests/{request_id}/deny", response_model=DependencyRequestRead)
async def deny_request(
    project_id: uuid.UUID,
    request_id: uuid.UUID,
    request: Request,
    body: DependencyDecision | None = None,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> DependencyRequestRead:
    return await _decide(
        False, project_id, request_id, body or DependencyDecision(), request, principal, db
    )


@router.post("/requests/{request_id}/revoke", response_model=DependencyRequestRead)
async def revoke_request(
    project_id: uuid.UUID,
    request_id: uuid.UUID,
    request: Request,
    body: DependencyDecision | None = None,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> DependencyRequestRead:
    row = await DependencyPolicyService(db).revoke(
        project_id, request_id, principal.user.id, body.note if body else None
    )
    project = await db.get(Project, project_id)
    info = request_info(request)
    await audit_service.record(
        db,
        action="dependency.revoke",
        result=AuditResult.ok,
        actor_id=principal.user.id,
        actor_email=principal.user.email,
        via=principal.via,
        target_type="project",
        target_id=project_id,
        organization_id=project.organization_id if project else None,
        client_ip=info.client_ip,
        request_id=info.request_id,
        detail={"package": row.package, "version": row.version, "hashes": row.hashes},
    )
    await db.commit()
    return DependencyRequestRead.model_validate(row)
