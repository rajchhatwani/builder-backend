"""Approvals inbox of the builder agent (B3-5). Viewers read, editors decide A-C, only the project
owner decides D, E and anything about AI-written hooks or hook effects (checked in the service).

GET  /projects/{project_id}/agent/approvals?state=pending     inbox (viewer)
GET  /projects/{project_id}/agent/approvals/{approval_id}     one (viewer)
POST /projects/{project_id}/agent/approvals/{approval_id}/decision   {approve, note?, plan?}  (editor; owner for D/E/hooks)

A decision only records the answer. The run resumes through the run's own resume endpoint.
"""

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.security import current_principal, request_info
from app.config import Settings, get_settings
from app.db import get_session
from app.models.agent import AiApproval
from app.models.enums import AuditResult
from app.models.project import Project
from app.schemas.agent_approval import ApprovalDecision, ApprovalRead
from app.services import audit_service
from app.services.access_service import Principal
from app.services.agent.approval_service import ApprovalService, requires_owner

router = APIRouter(prefix="/projects/{project_id}/agent/approvals", tags=["agent-approvals"])


def _read(svc: ApprovalService, row: AiApproval) -> ApprovalRead:
    out = ApprovalRead.model_validate(row)
    out.state = svc.effective_state(row)
    out.requires_owner = requires_owner(row.kind, row.payload, svc.policy)
    return out


@router.get("", response_model=list[ApprovalRead])
async def list_approvals(
    project_id: uuid.UUID,
    state: str | None = Query(default=None),
    run_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[ApprovalRead]:
    svc = ApprovalService(db, settings)
    return [_read(svc, r) for r in await svc.list(project_id, state=state, run_id=run_id, limit=limit)]


@router.get("/{approval_id}", response_model=ApprovalRead)
async def get_approval(
    project_id: uuid.UUID,
    approval_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ApprovalRead:
    svc = ApprovalService(db, settings)
    return _read(svc, await svc.get(project_id, approval_id))


@router.post("/{approval_id}/decision", response_model=ApprovalRead)
async def decide_approval(
    project_id: uuid.UUID,
    approval_id: uuid.UUID,
    body: ApprovalDecision,
    request: Request,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ApprovalRead:
    svc = ApprovalService(db, settings)
    row = await svc.decide(project_id, approval_id, principal.user.id, body.approve, body.note, body.plan)
    project = await db.get(Project, project_id)
    info = request_info(request)
    await audit_service.record(
        db,
        action="agent.approval.approve" if body.approve else "agent.approval.deny",
        result=AuditResult.ok,
        actor_id=principal.user.id,
        actor_email=principal.user.email,
        via=principal.via,
        target_type="agent_approval",
        target_id=row.id,
        project_id=project_id,
        organization_id=project.organization_id if project else None,
        client_ip=info.client_ip,
        request_id=info.request_id,
        detail={
            "kind": row.kind,
            "run_id": str(row.run_id),
            "spec_hash": row.bound_spec_hash,
            "commit": row.bound_commit or "",
            "risk_flags": ",".join(row.risk_flags),
            "plan_edited": "yes" if body.plan is not None else "no",
        },
    )
    await db.commit()
    return _read(svc, row)
