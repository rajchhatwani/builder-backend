import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_layers import weakens
from app.core.spec_models import Spec
from app.db import get_session
from app.exceptions import AppError
from app.schemas.spec import ValidationReport
from app.services.spec_service import SpecService

router = APIRouter(prefix="/projects/{project_id}", tags=["spec"])


@router.get("/spec", response_model=Spec)
async def get_spec(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Spec:
    return await SpecService(session).assemble(project_id)


@router.put("/spec", response_model=Spec)
async def put_spec(
    project_id: uuid.UUID,
    body: Spec,
    expected_version: int | None = Query(
        default=None,
        ge=1,
        description="The project version the caller last read. If it is no longer current the "
        "write is refused with 409 (details[0].current_version). Omitted: last write wins.",
    ),
    confirm_weakening: bool = Query(
        default=False,
        description="Required when the new spec gives some role more access than the saved one "
        "(else 409 access_weakened with the diff in details).",
    ),
    session: AsyncSession = Depends(get_session),
) -> Spec:
    service = SpecService(session)
    if not confirm_weakening:
        before = await service.assemble(project_id)
        after = body.model_copy()
        # a spec without these blocks leaves the saved ones as they are (see SpecService.replace)
        if after.auth is None:
            after.auth = before.auth
        if after.authorization is None:
            after.authorization = before.authorization
        gained = weakens(before, after)
        if gained:
            raise AppError(
                code="access_weakened",
                message=f"this spec gives {len({c['role'] for c in gained})} role(s) more "
                "access; review POST /access/diff and repeat with confirm_weakening",
                status_code=409,
                details=gained[:100],
            )
    return await service.replace(project_id, body, expected_version=expected_version)


@router.post("/validate", response_model=ValidationReport)
async def validate_project(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> ValidationReport:
    issues = await SpecService(session).validate(project_id)
    return ValidationReport(valid=not issues, issues=issues)
