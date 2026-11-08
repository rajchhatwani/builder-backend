"""Readiness board: one cheap, read-only summary of a project."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas.status import DismissBody, ProjectStatus
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
    3. sign-in not enabled and `consider_auth` not dismissed -> `consider_auth` (section `auth`);
    4. otherwise `generate` (section `generate`).
    """
    return await StatusService(session).get(project_id)


@router.post(
    "/dismiss",
    response_model=ProjectStatus,
    summary="Skip an optional next step (project editor); returns the new board",
)
async def dismiss_step(
    project_id: uuid.UUID, body: DismissBody, session: AsyncSession = Depends(get_session)
) -> ProjectStatus:
    """Stored per project. Only dismissable steps (`consider_auth`) are accepted; any other id is
    a 422. Idempotent. The step then appears in `dismissed_steps` with `dismissed: true` and is
    never `next_step`."""
    return await StatusService(session).dismiss(project_id, body.step)


@router.delete(
    "/dismiss/{step}",
    response_model=ProjectStatus,
    summary="Undo a dismissed next step (project editor); returns the new board",
)
async def undo_dismiss_step(
    project_id: uuid.UUID, step: str, session: AsyncSession = Depends(get_session)
) -> ProjectStatus:
    """Idempotent undo. Unknown or non-dismissable step ids are a 422."""
    return await StatusService(session).undo_dismiss(project_id, step)
