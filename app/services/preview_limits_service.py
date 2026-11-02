"""Admin side of the preview limits (B3-10): read/update platform defaults + kill switch and
per-org overrides. Every change is audit-logged with the before/after values."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AppError
from app.models.platform import Organization
from app.models.preview import LIVE_STATES, Preview, PreviewOrgLimits, PreviewPlatformSettings
from app.schemas.preview import (
    LimitsBody,
    PreviewLimitsRead,
    PreviewLimitsWrite,
    PreviewOrgLimitsRead,
    PreviewOrgLimitsRow,
    PreviewOrgLimitsWrite,
    PreviewUsageRead,
)
from app.services import audit_service
from app.services.access_service import Principal
from app.services.platform_auth_service import RequestInfo
from app.services.preview_limits import (
    BOUNDS,
    check_org_overrides,
    effective,
    resolve,
    validate_limits,
)


def _given(body: LimitsBody) -> dict[str, object]:
    return {k: v for k, v in body.model_dump().items() if v is not None}


class PreviewLimitsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _platform(self, create: bool = False) -> PreviewPlatformSettings | None:
        row = await self.db.get(PreviewPlatformSettings, 1)
        if row is None and create:
            row = PreviewPlatformSettings(id=1, kill_switch=False, limits={})
            self.db.add(row)
        return row

    async def read_platform(self) -> PreviewLimitsRead:
        row = await self._platform()
        return PreviewLimitsRead(
            kill_switch=bool(row and row.kill_switch),
            defaults=resolve(row.limits if row else None).as_dict(),
            bounds=BOUNDS,
            updated_at=row.updated_at if row else None,
            updated_by=row.updated_by if row else None,
        )

    async def update_platform(
        self, actor: Principal, body: PreviewLimitsWrite, info: RequestInfo
    ) -> PreviewLimitsRead:
        new_limits = validate_limits(_given(body.defaults)) if body.defaults else {}
        row = await self._platform(create=True)
        assert row is not None
        before_kill = row.kill_switch
        before_limits: dict[str, object] = dict(row.limits)
        if body.kill_switch is not None:
            row.kill_switch = body.kill_switch
        if new_limits:
            row.limits = {**row.limits, **new_limits}
        row.updated_by = actor.user.id
        row.updated_at = datetime.now(UTC)
        await audit_service.record(
            self.db,
            action="admin.preview_limits_update",
            actor_id=actor.user.id,
            actor_email=actor.user.email,
            target_type="preview_settings",
            target_id="platform",
            client_ip=info.client_ip,
            request_id=info.request_id,
            detail={
                "kill_switch": [before_kill, row.kill_switch],
                **{f"limit.{k}": [before_limits.get(k), v] for k, v in new_limits.items()},
            },
        )
        await self.db.commit()
        if body.kill_switch:
            # Switching off must stop running previews now, not at the next scheduled sweep.
            from app.services import preview_service

            preview_service.spawn_sweep()
        return await self.read_platform()

    async def _org(self, org_id: uuid.UUID) -> Organization:
        org = await self.db.get(Organization, org_id)
        if org is None:
            raise AppError("not_found", "organization not found", 404)
        return org

    async def _org_row(self, org_id: uuid.UUID) -> PreviewOrgLimits | None:
        return (
            await self.db.execute(
                select(PreviewOrgLimits).where(PreviewOrgLimits.organization_id == org_id)
            )
        ).scalar_one_or_none()

    async def read_org(self, org_id: uuid.UUID) -> PreviewOrgLimitsRead:
        await self._org(org_id)
        plat = await self._platform()
        row = await self._org_row(org_id)
        eff = effective(
            bool(plat and plat.kill_switch),
            plat.limits if plat else None,
            row.limits if row else None,
            row.enabled if row else True,
            row.allow_above_default if row else False,
        )
        return PreviewOrgLimitsRead(
            organization_id=org_id,
            enabled=row.enabled if row else True,
            allow_above_default=row.allow_above_default if row else False,
            overrides={k: v for k, v in (row.limits if row else {}).items()},  # type: ignore[misc]
            effective=eff.limits.as_dict(),
            kill_switch=bool(plat and plat.kill_switch),
            note=row.note if row else None,
            updated_at=row.updated_at if row else None,
        )

    async def set_org(
        self, actor: Principal, org_id: uuid.UUID, body: PreviewOrgLimitsWrite, info: RequestInfo
    ) -> PreviewOrgLimitsRead:
        await self._org(org_id)
        limits = validate_limits(_given(body.overrides))
        plat = await self._platform()
        check_org_overrides(plat.limits if plat else None, limits, body.allow_above_default)
        row = await self._org_row(org_id)
        before = {"enabled": row.enabled, "limits": dict(row.limits)} if row else None
        if row is None:
            row = PreviewOrgLimits(
                organization_id=org_id,
                enabled=body.enabled,
                allow_above_default=body.allow_above_default,
                limits=limits,
            )
            self.db.add(row)
        else:
            # a PUT replaces the whole override
            row.enabled, row.limits = body.enabled, dict(limits)
            row.allow_above_default = body.allow_above_default
        row.note, row.updated_by, row.updated_at = body.note, actor.user.id, datetime.now(UTC)
        await audit_service.record(
            self.db,
            action="admin.preview_org_limits_set",
            actor_id=actor.user.id,
            actor_email=actor.user.email,
            target_type="organization",
            target_id=org_id,
            organization_id=org_id,
            client_ip=info.client_ip,
            request_id=info.request_id,
            detail={
                "enabled": [before["enabled"] if before else True, body.enabled],
                **{f"limit.{k}": v for k, v in limits.items()},
            },
        )
        await self.db.commit()
        if not body.enabled:
            from app.services import preview_service

            preview_service.spawn_sweep()
        return await self.read_org(org_id)

    async def list_orgs(self, limit: int, offset: int) -> tuple[list[PreviewOrgLimitsRow], int]:
        total = (
            await self.db.execute(select(func.count()).select_from(PreviewOrgLimits))
        ).scalar_one()
        rows = (
            await self.db.execute(
                select(PreviewOrgLimits, Organization)
                .join(Organization, Organization.id == PreviewOrgLimits.organization_id)
                .order_by(Organization.name, Organization.id)
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return [
            PreviewOrgLimitsRow(
                organization_id=o.id,
                organization_name=o.name,
                organization_slug=o.slug,
                enabled=r.enabled,
                allow_above_default=r.allow_above_default,
                overrides={k: v for k, v in r.limits.items()},  # type: ignore[misc]
                note=r.note,
                updated_at=r.updated_at,
            )
            for r, o in rows
        ], total

    async def usage(self) -> PreviewUsageRead:
        counts = dict(
            (
                await self.db.execute(
                    select(Preview.state, func.count())
                    .where(Preview.state.in_(LIVE_STATES))
                    .group_by(Preview.state)
                )
            ).all()
        )
        by_state = {s: int(counts.get(s, 0)) for s in LIVE_STATES}
        plat = await self._platform()
        n_orgs = (
            await self.db.execute(select(func.count()).select_from(PreviewOrgLimits))
        ).scalar_one()
        return PreviewUsageRead(
            live=sum(by_state.values()),
            running=by_state["running"],
            by_state=by_state,
            orgs_with_overrides=int(n_orgs),
            kill_switch=bool(plat and plat.kill_switch),
        )

    async def clear_org(
        self, actor: Principal, org_id: uuid.UUID, info: RequestInfo
    ) -> PreviewOrgLimitsRead:
        await self._org(org_id)
        row = await self._org_row(org_id)
        if row is not None:
            await self.db.delete(row)
        await audit_service.record(
            self.db,
            action="admin.preview_org_limits_clear",
            actor_id=actor.user.id,
            actor_email=actor.user.email,
            target_type="organization",
            target_id=org_id,
            organization_id=org_id,
            client_ip=info.client_ip,
            request_id=info.request_id,
        )
        await self.db.commit()
        return await self.read_org(org_id)
