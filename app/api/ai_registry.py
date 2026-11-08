"""AI cost/settings (org admins) and the project registry (B3-7, B3-8).

    GET  /orgs/{slug}/ai/cost                      cost ledger page + month/total spend (admin)
    GET  /orgs/{slug}/ai/platform-budget           platform-wide spend vs hard cap
    GET  /orgs/{slug}/ai/settings                  key hint + budget (the key is never returned)
    PUT  /orgs/{slug}/ai/settings                  set/clear the BYO key and the budget (session)
    GET  /orgs/{slug}/registry/projects            projects registry view (admin)
    GET  /projects/{project_id}/registry/blocks    block versions       (viewer)
    POST /projects/{project_id}/registry/blocks    record one           (owner)
    GET|POST /projects/{project_id}/registry/hooks hooks ledger         (viewer | owner)
    POST /projects/{project_id}/registry/hooks/{entry_id}/approve       (owner)
    GET|POST /projects/{project_id}/registry/deps  dependency lock      (viewer | owner)
"""

import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination, pagination
from app.api.security import OrgContext, current_principal, org_context, request_info
from app.config import Settings, get_settings
from app.db import get_session
from app.models.enums import AuditResult
from app.schemas.ai_registry import (
    AiCostSummary,
    AiLedgerRead,
    AiPlatformBudgetRead,
    AiSettingsRead,
    AiSettingsWrite,
    BlockVersionRead,
    BlockVersionWrite,
    DepLockRead,
    DepLockWrite,
    HookEntryRead,
    HookEntryWrite,
    RegistryProjectRead,
)
from app.services import audit_service
from app.services.access_service import Principal
from app.services.ai.ledger import AiLedgerService, month_start
from app.services.ai.platform_cap import PlatformCap
from app.services.registry_service import RegistryService

org_router = APIRouter(prefix="/orgs", tags=["ai"])
router = APIRouter(prefix="/projects/{project_id}/registry", tags=["registry"])


def _settings_read(row: object | None) -> AiSettingsRead:
    return AiSettingsRead(
        has_api_key=bool(getattr(row, "api_key_enc", None)),
        api_key_hint=getattr(row, "api_key_hint", None),
        monthly_budget_micro_usd=getattr(row, "monthly_budget_micro_usd", None),
        approval_policy=getattr(row, "approval_policy", None),
    )


@org_router.get("/{slug}/ai/cost", response_model=AiCostSummary)
async def ai_cost(
    ctx: OrgContext = Depends(org_context),
    page: Pagination = Depends(pagination),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AiCostSummary:
    svc = AiLedgerService(db, settings)
    org_id = ctx.org.id
    rows, total = await svc.page(org_id, page.limit, page.offset)
    start = month_start()
    return AiCostSummary(
        month_start=start,
        month_cost_micro_usd=await svc.spent(org_id, start),
        total_cost_micro_usd=await svc.spent(org_id),
        monthly_budget_micro_usd=await svc.monthly_cap(org_id),
        items=[AiLedgerRead.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@org_router.get("/{slug}/ai/settings", response_model=AiSettingsRead)
async def get_ai_settings(
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AiSettingsRead:
    return _settings_read(await AiLedgerService(db, settings).get_settings(ctx.org.id))


@org_router.get("/{slug}/ai/platform-budget", response_model=AiPlatformBudgetRead)
async def get_platform_budget(
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AiPlatformBudgetRead:
    """Platform-wide real-model spend against the hard cap (what the build view budget bar shows)."""
    st = await PlatformCap(db, settings).status()
    cap, spent, reserved = st["cap"], int(st["spent"] or 0), int(st["reserved"] or 0)
    remaining = None if cap is None else max(cap - spent - reserved, 0)
    return AiPlatformBudgetRead(
        cap_micro_usd=cap, spent_micro_usd=spent, reserved_micro_usd=reserved, remaining_micro_usd=remaining
    )


@org_router.put("/{slug}/ai/settings", response_model=AiSettingsRead)
async def put_ai_settings(
    body: AiSettingsWrite,
    request: Request,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AiSettingsRead:
    row = await AiLedgerService(db, settings).update_settings(
        ctx.org.id,
        api_key=body.api_key.get_secret_value() if body.api_key else None,
        clear_api_key=body.clear_api_key,
        budget=body.monthly_budget_micro_usd,
        clear_budget=body.clear_budget,
        approval_policy=(
            body.approval_policy.model_dump(exclude_none=True) if body.approval_policy is not None else None
        ),
    )
    info = request_info(request)
    await audit_service.record(
        db,
        action="ai.settings.update",
        result=AuditResult.ok,
        actor_id=ctx.principal.user.id,
        actor_email=ctx.principal.user.email,
        via=ctx.principal.via,
        target_type="organization",
        target_id=ctx.org.id,
        organization_id=ctx.org.id,
        client_ip=info.client_ip,
        request_id=info.request_id,
        # Never the key: only what changed.
        detail={
            "key_set": body.api_key is not None,
            "key_cleared": body.clear_api_key,
            "budget_changed": body.monthly_budget_micro_usd is not None or body.clear_budget,
            "approval_policy_changed": body.approval_policy is not None,
        },
    )
    await db.commit()
    return _settings_read(row)


@org_router.get("/{slug}/registry/projects", response_model=list[RegistryProjectRead])
async def registry_projects(
    ctx: OrgContext = Depends(org_context), db: AsyncSession = Depends(get_session)
) -> list[RegistryProjectRead]:
    return await RegistryService(db).projects_view(ctx.org.id)


# -- project registry ------------------------------------------------------------------------


@router.get("/blocks", response_model=list[BlockVersionRead])
async def list_blocks(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> list[BlockVersionRead]:
    rows = await RegistryService(db).list_blocks(project_id)
    return [BlockVersionRead.model_validate(r) for r in rows]


@router.post("/blocks", response_model=BlockVersionRead, status_code=201)
async def add_block(
    project_id: uuid.UUID,
    body: BlockVersionWrite,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> BlockVersionRead:
    row, created = await RegistryService(db).add_block(project_id, body)
    await db.commit()
    response.status_code = 201 if created else 200
    return BlockVersionRead.model_validate(row)


@router.get("/hooks", response_model=list[HookEntryRead])
async def list_hooks(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> list[HookEntryRead]:
    rows = await RegistryService(db).list_hooks(project_id)
    return [HookEntryRead.model_validate(r) for r in rows]


@router.post("/hooks", response_model=HookEntryRead, status_code=201)
async def add_hook(
    project_id: uuid.UUID,
    body: HookEntryWrite,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> HookEntryRead:
    row, created = await RegistryService(db).add_hook(project_id, body)
    await db.commit()
    response.status_code = 201 if created else 200
    return HookEntryRead.model_validate(row)


@router.post("/hooks/{entry_id}/approve", response_model=HookEntryRead)
async def approve_hook(
    project_id: uuid.UUID,
    entry_id: uuid.UUID,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> HookEntryRead:
    row = await RegistryService(db).approve_hook(project_id, entry_id, principal.user.id)
    await db.commit()
    return HookEntryRead.model_validate(row)


@router.get("/deps", response_model=list[DepLockRead])
async def list_deps(
    project_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> list[DepLockRead]:
    rows = await RegistryService(db).list_deps(project_id)
    return [DepLockRead.model_validate(r) for r in rows]


@router.post("/deps", response_model=DepLockRead, status_code=201)
async def add_dep(
    project_id: uuid.UUID,
    body: DepLockWrite,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> DepLockRead:
    row, created = await RegistryService(db).add_dep(project_id, body)
    await db.commit()
    response.status_code = 201 if created else 200
    return DepLockRead.model_validate(row)
