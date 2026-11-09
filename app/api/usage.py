"""Usage metering (B4-5).

    GET /orgs/{slug}/usage                        per-metric used / limit / period / refused (member)
    GET /orgs/{slug}/usage/events                 usage events, newest first (member)
    PUT /orgs/{slug}/usage/limits/{metric}        set or clear (null) an org override (owner)
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination, pagination
from app.api.security import OrgContext, org_context, request_info
from app.db import get_session
from app.models.enums import AuditResult
from app.schemas.usage import (
    UsageEventPage,
    UsageEventRead,
    UsageLimitWrite,
    UsageMetricRead,
    UsageSummaryRead,
)
from app.services import audit_service
from app.services.usage_service import UsageService

org_router = APIRouter(prefix="/orgs", tags=["usage"])


@org_router.get("/{slug}/usage", response_model=UsageSummaryRead)
async def get_usage(
    ctx: OrgContext = Depends(org_context), db: AsyncSession = Depends(get_session)
) -> UsageSummaryRead:
    rows = await UsageService(db).usage_summary(ctx.org.id)
    return UsageSummaryRead(metrics=[UsageMetricRead(**r) for r in rows])


@org_router.get("/{slug}/usage/events", response_model=UsageEventPage)
async def get_usage_events(
    metric: str | None = None,
    ctx: OrgContext = Depends(org_context),
    page: Pagination = Depends(pagination),
    db: AsyncSession = Depends(get_session),
) -> UsageEventPage:
    rows, total = await UsageService(db).events(ctx.org.id, metric, page.limit, page.offset)
    return UsageEventPage(
        items=[UsageEventRead.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@org_router.put("/{slug}/usage/limits/{metric}", response_model=UsageSummaryRead)
async def put_usage_limit(
    metric: str,
    body: UsageLimitWrite,
    request: Request,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
) -> UsageSummaryRead:
    svc = UsageService(db)
    await svc.set_limit(ctx.org.id, metric, body.limit_value, ctx.principal.user.id)
    info = request_info(request)
    await audit_service.record(
        db,
        action="usage.limit.set",
        result=AuditResult.ok,
        actor_id=ctx.principal.user.id,
        actor_email=ctx.principal.user.email,
        via=ctx.principal.via,
        target_type="organization",
        target_id=ctx.org.id,
        organization_id=ctx.org.id,
        client_ip=info.client_ip,
        request_id=info.request_id,
        detail={"metric": metric, "limit_value": body.limit_value},
    )
    await db.commit()
    return UsageSummaryRead(metrics=[UsageMetricRead(**r) for r in await svc.usage_summary(ctx.org.id)])
