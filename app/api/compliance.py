"""Control mapping and evidence bundle of a project (D47), built from its spec.

Pattern of `generate/download`: any project member (viewer and up) may read; the project guard answers
404 to a non-member. A bundle download is audited (`compliance.evidence_download`)."""

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.security import current_principal
from app.db import get_session
from app.services import audit_service
from app.services.access_service import Principal
from app.services.compliance_service import (
    GENERATED_AT_RE,
    controls_for,
    default_generated_at,
    evidence_bundle,
)
from app.services.spec_service import SpecService

router = APIRouter(prefix="/projects/{project_id}/compliance", tags=["compliance"])

Framework = Literal["soc2", "hipaa", "pci"]


@router.get("/controls", summary="Control mapping of the spec for one framework")
async def get_controls(
    project_id: uuid.UUID,
    framework: Framework | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    spec = await SpecService(session).assemble(project_id)
    return controls_for(spec, framework)


@router.get(
    "/evidence",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}}},
    summary="Evidence bundle (zip) for one framework",
)
async def get_evidence(
    request: Request,
    project_id: uuid.UUID,
    framework: Framework,
    generated_at: str | None = Query(
        None, pattern=GENERATED_AT_RE.pattern,
        description="UTC stamp YYYY-MM-DDTHH:MM:SSZ written into the bundle. Default: derived from the spec hash, so the same spec gives identical bytes.",
    ),
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> Response:
    spec = await SpecService(session).assemble(project_id)
    stamp = generated_at or default_generated_at(spec)
    content = evidence_bundle(spec, framework, spec.project.name, stamp)
    await audit_service.record(
        session,
        action="compliance.evidence_download",
        actor_id=principal.user.id,
        actor_email=principal.user.email,
        via=principal.via,
        project_id=project_id,
        organization_id=getattr(request.state, "organization_id", None),
        target_type="project",
        target_id=project_id,
        request_id=getattr(request.state, "request_id", None),
        detail={"framework": framework},
    )
    await session.commit()
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="evidence-{framework}.zip"'},
    )
