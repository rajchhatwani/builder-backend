"""Admin operations console (CP-5V). Same surface and permissions as the other /admin routes.

GET  /admin/operations                                      jobs, idle TTL, reports, usage defaults, key provider, go-live  (settings:read)
POST /admin/operations/golive                               run the go-live checks now                                      (settings:write)
GET  /admin/organizations/{org_id_or_slug}/usage            per-metric used / limit / refused of any org                    (projects:read)
PUT  /admin/organizations/{org_id_or_slug}/usage/limits/{metric}  set or clear (null) an org override, audit-logged         (settings:write)
"""

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.security import request_info, require_admin
from app.config import Settings, get_settings
from app.db import get_session
from app.exceptions import AppError
from app.models.enums import AuditResult
from app.models.platform import Organization
from app.schemas.ops import GoliveRead, OperationsRead
from app.schemas.usage import UsageLimitWrite, UsageMetricRead, UsageSummaryRead
from app.services import audit_service, ops_service
from app.services.access_service import Principal
from app.services.usage_service import UsageService

router = APIRouter(prefix="/admin", tags=["admin"])

NEEDS_SETTINGS_READ = Depends(require_admin("settings:read"))
NEEDS_SETTINGS_WRITE = Depends(require_admin("settings:write"))
NEEDS_PROJECTS_READ = Depends(require_admin("projects:read"))


@router.get("/operations", response_model=OperationsRead)
async def operations(
    _: Principal = NEEDS_SETTINGS_READ,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> OperationsRead:
    return OperationsRead.model_validate(await ops_service.operations_overview(db, settings))


@router.post("/operations/golive", response_model=GoliveRead)
async def run_golive(
    _: Principal = NEEDS_SETTINGS_WRITE,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> GoliveRead:
    return GoliveRead.model_validate(await ops_service.golive_checks(db, settings))


async def _org(db: AsyncSession, key: str) -> Organization:
    try:
        cond = Organization.id == uuid.UUID(key)
    except ValueError:
        cond = Organization.slug == key
    org = (await db.execute(select(Organization).where(cond))).scalar_one_or_none()
    if org is None:
        raise AppError("not_found", "organization not found", 404)
    return org


async def _summary(db: AsyncSession, org_id: uuid.UUID) -> UsageSummaryRead:
    rows = await UsageService(db).usage_summary(org_id)
    return UsageSummaryRead(metrics=[UsageMetricRead(**r) for r in rows])


@router.get("/organizations/{org_id_or_slug}/usage", response_model=UsageSummaryRead)
async def org_usage(
    org_id_or_slug: str,
    _: Principal = NEEDS_PROJECTS_READ,
    db: AsyncSession = Depends(get_session),
) -> UsageSummaryRead:
    return await _summary(db, (await _org(db, org_id_or_slug)).id)


@router.put("/organizations/{org_id_or_slug}/usage/limits/{metric}", response_model=UsageSummaryRead)
async def set_org_usage_limit(
    org_id_or_slug: str,
    metric: str,
    body: UsageLimitWrite,
    request: Request,
    principal: Principal = NEEDS_SETTINGS_WRITE,
    db: AsyncSession = Depends(get_session),
) -> UsageSummaryRead:
    org = await _org(db, org_id_or_slug)
    svc = UsageService(db)
    old = await svc.limit_for(org.id, metric)  # 422/404 for an unknown metric
    await svc.set_limit(org.id, metric, body.limit_value, principal.user.id)
    info = request_info(request)
    await audit_service.record(
        db,
        action="admin.usage.limit.set",
        result=AuditResult.ok,
        actor_id=principal.user.id,
        actor_email=principal.user.email,
        via=principal.via,
        target_type="organization",
        target_id=org.id,
        organization_id=org.id,
        client_ip=info.client_ip,
        request_id=info.request_id,
        detail={"metric": metric, "limit_value": body.limit_value, "previous_limit": old},
    )
    await db.commit()
    return await _summary(db, org.id)
