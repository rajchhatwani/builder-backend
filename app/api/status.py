"""Readiness board: one cheap, read-only summary of a project."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas.status import ProjectStatus
from app.services.status_service import StatusService

router = APIRouter(prefix="/projects/{project_id}/status", tags=["status"])


@router.get("", response_model=ProjectStatus, summary="Readiness board: issues, counts, next step")
async def project_status(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> ProjectStatus:
    """One validate call over the current spec; no generation, nothing is written.

    `ready` = at least one entity and no validation issue. `issues` are the validation issues
    (path, code, message). `sections` lists 13 areas with `configured` and `issue_count` (issues
    are assigned to an area by path; auth.roles/auth.permissions and `authz.*` codes belong to
    `authorization`, sequences and lists to `settings`, anything else unknown to `model`).

    `next_step` (exactly one, first match wins):
    1. any issue -> `fix_issues`, section = area of the first issue in validation order;
    2. no entities -> `add_entity` (section `model`);
    3. sign-in not enabled -> `consider_auth` (section `auth`);
    4. otherwise `generate` (section `generate`).
    """
    return await StatusService(session).get(project_id)
