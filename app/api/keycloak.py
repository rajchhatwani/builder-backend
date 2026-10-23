"""Routes for a project's Keycloak settings and the guarded provider switch."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas.keycloak import (
    KeycloakConfigRead,
    KeycloakConfigWrite,
    KeycloakImpact,
    KeycloakSwitchRequest,
)
from app.services.keycloak_service import KeycloakService

router = APIRouter(prefix="/projects/{project_id}/keycloak", tags=["keycloak"])


async def _read(service: KeycloakService, project_id: uuid.UUID) -> KeycloakConfigRead:
    config = await service.get(project_id)
    read = KeycloakConfigRead.model_validate(config)
    read.active = await service.is_active(project_id)
    return read


@router.get("", response_model=KeycloakConfigRead, summary="Get the Keycloak settings")
async def get_keycloak(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> KeycloakConfigRead:
    return await _read(KeycloakService(session), project_id)


@router.put(
    "",
    response_model=KeycloakConfigRead,
    summary="Create or replace the Keycloak settings (does not switch the provider)",
)
async def put_keycloak(
    project_id: uuid.UUID,
    body: KeycloakConfigWrite,
    session: AsyncSession = Depends(get_session),
) -> KeycloakConfigRead:
    service = KeycloakService(session)
    await service.put(project_id, body)
    return await _read(service, project_id)


@router.get(
    "/impact",
    response_model=KeycloakImpact,
    summary="What turning Keycloak on or off would change",
)
async def keycloak_impact(
    project_id: uuid.UUID, action: str, session: AsyncSession = Depends(get_session)
) -> KeycloakImpact:
    return await KeycloakService(session).impact(project_id, action)


@router.post("/enable", response_model=KeycloakConfigRead, summary="Use Keycloak for this project")
async def enable_keycloak(
    project_id: uuid.UUID,
    body: KeycloakSwitchRequest,
    session: AsyncSession = Depends(get_session),
) -> KeycloakConfigRead:
    service = KeycloakService(session)
    await service.switch(project_id, "enable", confirm=body.confirm)
    return await _read(service, project_id)


@router.post("/disable", response_model=KeycloakConfigRead, summary="Go back to built-in auth")
async def disable_keycloak(
    project_id: uuid.UUID,
    body: KeycloakSwitchRequest,
    session: AsyncSession = Depends(get_session),
) -> KeycloakConfigRead:
    service = KeycloakService(session)
    await service.switch(project_id, "disable", confirm=body.confirm)
    return await _read(service, project_id)
