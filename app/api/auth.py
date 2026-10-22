"""API routers for auth configuration, roles, permissions, and custom fields.

All routes are nested under /projects/{project_id}/auth/... per the plan.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination, pagination
from app.db import get_session
from app.schemas.auth_config import AuthConfigCreate, AuthConfigRead, AuthConfigUpdate
from app.schemas.auth_custom_field import (
    AuthCustomFieldCreate,
    AuthCustomFieldRead,
    AuthCustomFieldUpdate,
)
from app.schemas.auth_secrets import AuthSecretsStatus, AuthSecretsWrite
from app.schemas.common import Page
from app.schemas.project_permission import (
    ProjectPermissionBulkUpsert,
    ProjectPermissionRead,
    ProjectPermissionUpdate,
)
from app.schemas.project_role import ProjectRoleCreate, ProjectRoleRead, ProjectRoleUpdate
from app.services.auth_config_service import AuthConfigService
from app.services.auth_custom_field_service import AuthCustomFieldService
from app.services.auth_secrets_service import AuthSecretsService
from app.services.project_permission_service import ProjectPermissionService
from app.services.project_role_service import ProjectRoleService

router = APIRouter(tags=["auth"])

# ── Auth Config ───────────────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/auth",
    response_model=AuthConfigRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create auth configuration for a project",
)
async def create_auth_config(
    project_id: uuid.UUID,
    body: AuthConfigCreate,
    session: AsyncSession = Depends(get_session),
) -> AuthConfigRead:
    config = await AuthConfigService(session).create(project_id, body)
    return AuthConfigRead.model_validate(config)


@router.get(
    "/projects/{project_id}/auth",
    response_model=AuthConfigRead,
    summary="Get auth configuration for a project",
)
async def get_auth_config(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> AuthConfigRead:
    config = await AuthConfigService(session).get(project_id)
    return AuthConfigRead.model_validate(config)


@router.patch(
    "/projects/{project_id}/auth",
    response_model=AuthConfigRead,
    summary="Update auth configuration for a project",
)
async def update_auth_config(
    project_id: uuid.UUID,
    body: AuthConfigUpdate,
    session: AsyncSession = Depends(get_session),
) -> AuthConfigRead:
    config = await AuthConfigService(session).update(project_id, body)
    return AuthConfigRead.model_validate(config)


# ── Secrets (write-only — response is status booleans, never plaintext) ───────


@router.put(
    "/projects/{project_id}/auth/secrets",
    response_model=AuthSecretsStatus,
    summary="Store encrypted credentials for SMTP / SMS providers",
)
async def upsert_auth_secrets(
    project_id: uuid.UUID,
    body: AuthSecretsWrite,
    session: AsyncSession = Depends(get_session),
) -> AuthSecretsStatus:
    """Accepts plaintext credentials; stores them AES-encrypted at rest.

    The response never includes plaintext values — only boolean flags
    indicating which credential groups are configured.
    """
    return await AuthSecretsService(session).upsert(project_id, body)


@router.get(
    "/projects/{project_id}/auth/secrets/status",
    response_model=AuthSecretsStatus,
    summary="Check which credential groups are configured (booleans only)",
)
async def get_auth_secrets_status(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> AuthSecretsStatus:
    """Returns configuration booleans — never plaintext or ciphertext."""
    return await AuthSecretsService(session).status(project_id)


# ── Roles ─────────────────────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/roles",
    response_model=ProjectRoleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a role for a project",
)
async def create_role(
    project_id: uuid.UUID,
    body: ProjectRoleCreate,
    session: AsyncSession = Depends(get_session),
) -> ProjectRoleRead:
    role = await ProjectRoleService(session).create(project_id, body)
    return ProjectRoleRead.model_validate(role)


@router.get(
    "/projects/{project_id}/roles",
    response_model=Page[ProjectRoleRead],
    summary="List roles for a project",
)
async def list_roles(
    project_id: uuid.UUID,
    page: Pagination = Depends(pagination),
    session: AsyncSession = Depends(get_session),
) -> Page[ProjectRoleRead]:
    roles, total = await ProjectRoleService(session).list(project_id, page.limit, page.offset)
    return Page[ProjectRoleRead](
        items=[ProjectRoleRead.model_validate(r) for r in roles],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/roles/{role_id}",
    response_model=ProjectRoleRead,
    summary="Get a role by ID",
)
async def get_role(
    role_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> ProjectRoleRead:
    role = await ProjectRoleService(session).get(role_id)
    return ProjectRoleRead.model_validate(role)


@router.patch(
    "/roles/{role_id}",
    response_model=ProjectRoleRead,
    summary="Update a role",
)
async def update_role(
    role_id: uuid.UUID,
    body: ProjectRoleUpdate,
    session: AsyncSession = Depends(get_session),
) -> ProjectRoleRead:
    role = await ProjectRoleService(session).update(role_id, body)
    return ProjectRoleRead.model_validate(role)


@router.delete(
    "/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a role",
)
async def delete_role(
    role_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    await ProjectRoleService(session).delete(role_id)


# ── Permissions ───────────────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/permissions",
    response_model=list[ProjectPermissionRead],
    status_code=status.HTTP_200_OK,
    summary="Bulk upsert permissions for a project (returns full updated list)",
)
async def bulk_upsert_permissions(
    project_id: uuid.UUID,
    body: ProjectPermissionBulkUpsert,
    session: AsyncSession = Depends(get_session),
) -> list[ProjectPermissionRead]:
    perms = await ProjectPermissionService(session).bulk_upsert(project_id, body)
    return [ProjectPermissionRead.model_validate(p) for p in perms]


@router.get(
    "/projects/{project_id}/permissions",
    response_model=Page[ProjectPermissionRead],
    summary="List permissions for a project",
)
async def list_permissions(
    project_id: uuid.UUID,
    page: Pagination = Depends(pagination),
    session: AsyncSession = Depends(get_session),
) -> Page[ProjectPermissionRead]:
    perms, total = await ProjectPermissionService(session).list_paginated(
        project_id, page.limit, page.offset
    )
    return Page[ProjectPermissionRead](
        items=[ProjectPermissionRead.model_validate(p) for p in perms],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/permissions/{permission_id}",
    response_model=ProjectPermissionRead,
    summary="Get a permission entry by ID",
)
async def get_permission(
    permission_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> ProjectPermissionRead:
    perm = await ProjectPermissionService(session).get(permission_id)
    return ProjectPermissionRead.model_validate(perm)


@router.patch(
    "/permissions/{permission_id}",
    response_model=ProjectPermissionRead,
    summary="Update a permission entry",
)
async def update_permission(
    permission_id: uuid.UUID,
    body: ProjectPermissionUpdate,
    session: AsyncSession = Depends(get_session),
) -> ProjectPermissionRead:
    perm = await ProjectPermissionService(session).update(permission_id, body)
    return ProjectPermissionRead.model_validate(perm)


@router.delete(
    "/permissions/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a permission entry",
)
async def delete_permission(
    permission_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    await ProjectPermissionService(session).delete(permission_id)


# ── Auth Custom Fields ────────────────────────────────────────────────────────


@router.post(
    "/projects/{project_id}/auth/custom-fields",
    response_model=AuthCustomFieldRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a custom registration field to a project",
)
async def create_custom_field(
    project_id: uuid.UUID,
    body: AuthCustomFieldCreate,
    session: AsyncSession = Depends(get_session),
) -> AuthCustomFieldRead:
    field = await AuthCustomFieldService(session).create(project_id, body)
    return AuthCustomFieldRead.model_validate(field)


@router.get(
    "/projects/{project_id}/auth/custom-fields",
    response_model=Page[AuthCustomFieldRead],
    summary="List custom registration fields for a project",
)
async def list_custom_fields(
    project_id: uuid.UUID,
    page: Pagination = Depends(pagination),
    session: AsyncSession = Depends(get_session),
) -> Page[AuthCustomFieldRead]:
    fields, total = await AuthCustomFieldService(session).list(
        project_id, page.limit, page.offset
    )
    return Page[AuthCustomFieldRead](
        items=[AuthCustomFieldRead.model_validate(f) for f in fields],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/auth/custom-fields/{field_id}",
    response_model=AuthCustomFieldRead,
    summary="Get a custom registration field by ID",
)
async def get_custom_field(
    field_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> AuthCustomFieldRead:
    field = await AuthCustomFieldService(session).get(field_id)
    return AuthCustomFieldRead.model_validate(field)


@router.patch(
    "/auth/custom-fields/{field_id}",
    response_model=AuthCustomFieldRead,
    summary="Update a custom registration field",
)
async def update_custom_field(
    field_id: uuid.UUID,
    body: AuthCustomFieldUpdate,
    session: AsyncSession = Depends(get_session),
) -> AuthCustomFieldRead:
    field = await AuthCustomFieldService(session).update(field_id, body)
    return AuthCustomFieldRead.model_validate(field)


@router.delete(
    "/auth/custom-fields/{field_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a custom registration field",
)
async def delete_custom_field(
    field_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    await AuthCustomFieldService(session).delete(field_id)
