import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.platform import PlatformUser, ProjectMember
from app.schemas.account import MemberAdd, MemberRead, MemberUpdate
from app.services.member_service import MemberService

# Guarded by the router-level dependency in app/main.py: reading members needs the viewer role,
# every change needs owner (app.core.platform_authz).
router = APIRouter(prefix="/projects/{project_id}/members", tags=["members"])


def _read(member: ProjectMember, user: PlatformUser) -> MemberRead:
    return MemberRead(
        user_id=user.id,
        email=user.email,
        name=user.name,
        role=member.role,
        created_at=member.created_at,
    )


@router.get("", response_model=list[MemberRead])
async def list_members(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> list[MemberRead]:
    return [_read(m, u) for m, u in await MemberService(db).list(project_id)]


@router.post("", response_model=MemberRead, status_code=status.HTTP_201_CREATED)
async def add_member(
    project_id: uuid.UUID, body: MemberAdd, db: AsyncSession = Depends(get_session)
) -> MemberRead:
    member, user = await MemberService(db).add(project_id, body.email, body.role)
    return _read(member, user)


@router.patch("/{user_id}", response_model=MemberRead)
async def update_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    body: MemberUpdate,
    db: AsyncSession = Depends(get_session),
) -> MemberRead:
    member, user = await MemberService(db).set_role(project_id, user_id, body.role)
    return _read(member, user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    project_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> None:
    await MemberService(db).remove(project_id, user_id)
