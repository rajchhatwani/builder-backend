"""Upgrade proposals (P3) and the project scorecard (P4).

Reads need the viewer role and writes the editor role (the project guard decides by method, like every
project route). A proposal is a record plus a downloadable patch: nothing is merged for the owner."""

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.security import current_principal
from app.db import get_session
from app.schemas.common import Page
from app.schemas.upgrade import Scorecard, UpgradeProposalDetail, UpgradeProposalSummary
from app.services.access_service import Principal
from app.services.upgrade_service import UpgradeService, detail, summary

router = APIRouter(prefix="/projects/{project_id}", tags=["upgrades"])


@router.get("/scorecard", response_model=Scorecard)
async def get_scorecard(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Scorecard:
    return Scorecard.model_validate(await UpgradeService(session).scorecard(project_id))


@router.post("/upgrades", response_model=UpgradeProposalDetail, status_code=201)
async def create_upgrade(
    request: Request,
    project_id: uuid.UUID,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> UpgradeProposalDetail:
    row = await UpgradeService(session).create(
        project_id, principal, getattr(request.state, "organization_id", None),
        getattr(request.state, "request_id", None),
    )
    return detail(row)


@router.get("/upgrades", response_model=Page[UpgradeProposalSummary])
async def list_upgrades(
    project_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> Page[UpgradeProposalSummary]:
    rows, total = await UpgradeService(session).list(project_id, limit, offset)
    return Page[UpgradeProposalSummary](items=[summary(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/upgrades/{proposal_id}", response_model=UpgradeProposalDetail)
async def get_upgrade(
    project_id: uuid.UUID, proposal_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> UpgradeProposalDetail:
    return detail(await UpgradeService(session).get(project_id, proposal_id))


@router.get(
    "/upgrades/{proposal_id}/patch",
    response_class=Response,
    responses={200: {"content": {"text/x-diff": {}}}},
)
async def get_patch(
    project_id: uuid.UUID, proposal_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> Response:
    row = await UpgradeService(session).get(project_id, proposal_id)
    return Response(
        content=row.patch_text,
        media_type="text/x-diff",
        headers={"Content-Disposition": f'attachment; filename="upgrade-{row.id}.patch"'},
    )


async def _decide(request: Request, project_id: uuid.UUID, proposal_id: uuid.UUID, status: str,
                  principal: Principal, session: AsyncSession) -> UpgradeProposalDetail:
    row = await UpgradeService(session).decide(
        project_id, proposal_id, status, principal, getattr(request.state, "organization_id", None),
        getattr(request.state, "request_id", None),
    )
    return detail(row)


@router.post("/upgrades/{proposal_id}/dismiss", response_model=UpgradeProposalDetail)
async def dismiss_upgrade(
    request: Request, project_id: uuid.UUID, proposal_id: uuid.UUID,
    principal: Principal = Depends(current_principal), session: AsyncSession = Depends(get_session),
) -> UpgradeProposalDetail:
    return await _decide(request, project_id, proposal_id, "dismissed", principal, session)


@router.post("/upgrades/{proposal_id}/applied", response_model=UpgradeProposalDetail)
async def mark_applied(
    request: Request, project_id: uuid.UUID, proposal_id: uuid.UUID,
    principal: Principal = Depends(current_principal), session: AsyncSession = Depends(get_session),
) -> UpgradeProposalDetail:
    return await _decide(request, project_id, proposal_id, "applied", principal, session)
