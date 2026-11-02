"""Admin endpoints for the preview runtime limits (B3-10).

GET    /admin/preview-limits                      read platform defaults, kill switch, bounds (settings:read)
PUT    /admin/preview-limits                      update kill switch and/or default limits   (settings:write)
GET    /admin/preview-limits/usage                live/running preview counts                (settings:read)
GET    /admin/preview-limits/orgs                 paginated list of org overrides            (settings:read)
GET    /admin/preview-limits/orgs/{org_id}        an org's override + effective limits       (settings:read)
PUT    /admin/preview-limits/orgs/{org_id}        replace an org's override                  (settings:write)
DELETE /admin/preview-limits/orgs/{org_id}        remove the override                        (settings:write)
"""

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination, pagination
from app.api.security import request_info, require_admin
from app.db import get_session
from app.schemas.preview import (
    PreviewLimitsRead,
    PreviewLimitsWrite,
    PreviewOrgLimitsRead,
    PreviewOrgLimitsRow,
    PreviewOrgLimitsWrite,
    PreviewUsageRead,
)
from app.schemas.common import Page
from app.services.access_service import Principal
from app.services.preview_limits_service import PreviewLimitsService

router = APIRouter(prefix="/admin/preview-limits", tags=["admin"])
NEEDS_READ = Depends(require_admin("settings:read"))
NEEDS_WRITE = Depends(require_admin("settings:write"))


@router.get("", response_model=PreviewLimitsRead)
async def read_limits(
    _: Principal = NEEDS_READ, db: AsyncSession = Depends(get_session)
) -> PreviewLimitsRead:
    return await PreviewLimitsService(db).read_platform()


@router.put("", response_model=PreviewLimitsRead)
async def update_limits(
    body: PreviewLimitsWrite,
    request: Request,
    principal: Principal = NEEDS_WRITE,
    db: AsyncSession = Depends(get_session),
) -> PreviewLimitsRead:
    return await PreviewLimitsService(db).update_platform(principal, body, request_info(request))


@router.get("/usage", response_model=PreviewUsageRead)
async def usage(
    _: Principal = NEEDS_READ, db: AsyncSession = Depends(get_session)
) -> PreviewUsageRead:
    return await PreviewLimitsService(db).usage()


@router.get("/orgs", response_model=Page[PreviewOrgLimitsRow])
async def list_org_limits(
    page: Pagination = Depends(pagination),
    _: Principal = NEEDS_READ,
    db: AsyncSession = Depends(get_session),
) -> Page[PreviewOrgLimitsRow]:
    items, total = await PreviewLimitsService(db).list_orgs(page.limit, page.offset)
    return Page[PreviewOrgLimitsRow](items=items, total=total, limit=page.limit, offset=page.offset)


@router.get("/orgs/{org_id}", response_model=PreviewOrgLimitsRead)
async def read_org_limits(
    org_id: uuid.UUID, _: Principal = NEEDS_READ, db: AsyncSession = Depends(get_session)
) -> PreviewOrgLimitsRead:
    return await PreviewLimitsService(db).read_org(org_id)


@router.put("/orgs/{org_id}", response_model=PreviewOrgLimitsRead)
async def set_org_limits(
    org_id: uuid.UUID,
    body: PreviewOrgLimitsWrite,
    request: Request,
    principal: Principal = NEEDS_WRITE,
    db: AsyncSession = Depends(get_session),
) -> PreviewOrgLimitsRead:
    return await PreviewLimitsService(db).set_org(principal, org_id, body, request_info(request))


@router.delete("/orgs/{org_id}", response_model=PreviewOrgLimitsRead)
async def clear_org_limits(
    org_id: uuid.UUID,
    request: Request,
    principal: Principal = NEEDS_WRITE,
    db: AsyncSession = Depends(get_session),
) -> PreviewOrgLimitsRead:
    return await PreviewLimitsService(db).clear_org(principal, org_id, request_info(request))
