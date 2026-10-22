import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.spec_models import Spec
from app.db import get_session
from app.schemas.spec import ValidationReport
from app.services.spec_service import SpecService

router = APIRouter(prefix="/projects/{project_id}", tags=["spec"])


@router.get("/spec", response_model=Spec)
async def get_spec(project_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Spec:
    return await SpecService(session).assemble(project_id)


@router.put("/spec", response_model=Spec)
async def put_spec(
    project_id: uuid.UUID, body: Spec, session: AsyncSession = Depends(get_session)
) -> Spec:
    return await SpecService(session).replace(project_id, body)


@router.post("/validate", response_model=ValidationReport)
async def validate_project(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> ValidationReport:
    issues = await SpecService(session).validate(project_id)
    return ValidationReport(valid=not issues, issues=issues)
