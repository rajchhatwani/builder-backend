"""Routes for a project's storage settings and the guarded switch."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas.storage import (
    StorageConfigRead,
    StorageConfigWrite,
    StorageImpact,
    StorageIssues,
    StorageSwitchRequest,
)
from app.services.spec_service import SpecService
from app.services.storage_service import StorageService

router = APIRouter(prefix="/projects/{project_id}/storage", tags=["storage"])


@router.get("", response_model=StorageConfigRead, summary="Get the storage settings")
async def get_storage(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> StorageConfigRead:
    return StorageConfigRead.model_validate(await StorageService(session).get(project_id))


@router.put(
    "",
    response_model=StorageConfigRead,
    summary="Create or replace the storage settings (does not switch storage on or off)",
)
async def put_storage(
    project_id: uuid.UUID,
    body: StorageConfigWrite,
    session: AsyncSession = Depends(get_session),
) -> StorageConfigRead:
    return StorageConfigRead.model_validate(await StorageService(session).put(project_id, body))


@router.get(
    "/issues",
    response_model=StorageIssues,
    summary="Problems with the storage settings and file fields (no side effects)",
)
async def storage_issues(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> StorageIssues:
    found = await SpecService(session).validate(project_id)
    relevant = [
        i.model_dump()
        for i in found
        if i.path.startswith("storage") or i.code == "storage_required"
    ]
    return StorageIssues(issues=relevant)


@router.get(
    "/impact", response_model=StorageImpact, summary="What turning storage on or off changes"
)
async def storage_impact(
    project_id: uuid.UUID, action: str, session: AsyncSession = Depends(get_session)
) -> StorageImpact:
    return await StorageService(session).impact(project_id, action)


@router.post("/enable", response_model=StorageConfigRead, summary="Turn file storage on")
async def enable_storage(
    project_id: uuid.UUID,
    body: StorageSwitchRequest,
    session: AsyncSession = Depends(get_session),
) -> StorageConfigRead:
    config = await StorageService(session).switch(project_id, "enable", confirm=body.confirm)
    return StorageConfigRead.model_validate(config)


@router.post("/disable", response_model=StorageConfigRead, summary="Turn file storage off")
async def disable_storage(
    project_id: uuid.UUID,
    body: StorageSwitchRequest,
    session: AsyncSession = Depends(get_session),
) -> StorageConfigRead:
    config = await StorageService(session).switch(project_id, "disable", confirm=body.confirm)
    return StorageConfigRead.model_validate(config)
