"""Member management and project-scoped token management.

Member roles: viewer (read), editor (change spec), owner (manage people + credentials + deletion).
MCP access: a separate per-member flag set by the project owner. Being a member does not
automatically grant MCP access; the owner must explicitly enable it.

Project token endpoints let a project owner see and revoke API tokens that are pinned to their
project, without needing platform-admin access.
"""

import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.security import guard, request_info
from app.db import get_session
from app.models.platform import PlatformUser, ProjectMember
from app.schemas.account import (
    ApiTokenRead,
    MemberAdd,
    MemberMcpUpdate,
    MemberRead,
    MemberUpdate,
    ProjectTokenRead,
)
from app.services.access_service import Principal
from app.services.api_token_service import ApiTokenService
from app.services.member_service import MemberService

# Guarded by the router-level dependency in app/main.py.
router = APIRouter(prefix="/projects/{project_id}", tags=["members"])


def _read(member: ProjectMember, user: PlatformUser) -> MemberRead:
    return MemberRead(
        user_id=user.id,
        email=user.email,
        name=user.name,
        role=member.role,
        mcp_enabled=member.mcp_enabled,
        created_at=member.created_at,
    )


# -- members ---------------------------------------------------------------------------


@router.get("/members", response_model=list[MemberRead])
async def list_members(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> list[MemberRead]:
    return [_read(m, u) for m, u in await MemberService(db).list(project_id)]


@router.post("/members", response_model=MemberRead, status_code=status.HTTP_201_CREATED)
async def add_member(
    project_id: uuid.UUID, body: MemberAdd, db: AsyncSession = Depends(get_session)
) -> MemberRead:
    member, user = await MemberService(db).add(
        project_id, body.email, body.role, mcp_enabled=body.mcp_enabled
    )
    return _read(member, user)


@router.patch("/members/{user_id}", response_model=MemberRead)
async def update_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    body: MemberUpdate,
    db: AsyncSession = Depends(get_session),
) -> MemberRead:
    member, user = await MemberService(db).set_role(project_id, user_id, body.role)
    return _read(member, user)


@router.patch("/members/{user_id}/mcp", response_model=MemberRead)
async def set_member_mcp(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    body: MemberMcpUpdate,
    db: AsyncSession = Depends(get_session),
) -> MemberRead:
    """Enable or disable MCP access for a member. Owner only (enforced by platform_authz)."""
    member, user = await MemberService(db).set_mcp_enabled(project_id, user_id, body.mcp_enabled)
    return _read(member, user)


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    project_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> None:
    await MemberService(db).remove(project_id, user_id)


# -- project-scoped token management (owner only) --------------------------------------


@router.get("/tokens", response_model=list[ProjectTokenRead])
async def list_project_tokens(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
) -> list[ProjectTokenRead]:
    """List all active tokens pinned to this project. Owner only."""
    pairs = await ApiTokenService(db).list_for_project(project_id)
    result = []
    for tok, usr in pairs:
        base = ApiTokenRead.model_validate(tok)
        result.append(
            ProjectTokenRead(
                **base.model_dump(),
                user_id=usr.id,
                user_email=usr.email,
            )
        )
    return result


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_project_token(
    project_id: uuid.UUID,
    token_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(guard),
    db: AsyncSession = Depends(get_session),
) -> None:
    """Revoke a token pinned to this project. Owner only."""
    await ApiTokenService(db).revoke_for_project(
        principal.user, project_id, token_id, request_info(request)
    )
