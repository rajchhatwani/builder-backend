"""Cost ledger writes/reads, per-org settings (BYO key) and the budget cap check."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import crypto
from app.exceptions import AppError
from app.models.ai_ledger import AiCostLedger, AiOrgSettings
from app.services.ai.base import Usage
from app.services.ai.pricing import cost_micro_usd, price_table


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def budget_exceeded(spent: int, cap: int | None) -> bool:
    return cap is not None and spent >= cap


class AiLedgerService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def get_settings(self, org_id: uuid.UUID) -> AiOrgSettings | None:
        return (
            await self.session.execute(
                select(AiOrgSettings).where(AiOrgSettings.organization_id == org_id)
            )
        ).scalar_one_or_none()

    async def update_settings(
        self,
        org_id: uuid.UUID,
        *,
        api_key: str | None,
        clear_api_key: bool,
        budget: int | None,
        clear_budget: bool,
    ) -> AiOrgSettings:
        row = await self.get_settings(org_id)
        if row is None:
            row = AiOrgSettings(organization_id=org_id)
            self.session.add(row)
        if clear_api_key:
            row.api_key_enc = None
            row.api_key_hint = None
        if api_key is not None:
            row.api_key_enc = crypto.encrypt(api_key)
            row.api_key_hint = api_key[-4:]
        if clear_budget:
            row.monthly_budget_micro_usd = None
        if budget is not None:
            row.monthly_budget_micro_usd = budget
        await self.session.flush()
        return row

    async def api_key(self, org_id: uuid.UUID) -> str | None:
        row = await self.get_settings(org_id)
        return crypto.decrypt(row.api_key_enc) if row is not None else None

    async def monthly_cap(self, org_id: uuid.UUID) -> int | None:
        row = await self.get_settings(org_id)
        if row is not None and row.monthly_budget_micro_usd is not None:
            return row.monthly_budget_micro_usd
        return self.settings.ai_default_monthly_budget_micro_usd

    async def spent(self, org_id: uuid.UUID, since: datetime | None = None) -> int:
        stmt = select(func.coalesce(func.sum(AiCostLedger.cost_micro_usd), 0)).where(
            AiCostLedger.organization_id == org_id
        )
        if since is not None:
            stmt = stmt.where(AiCostLedger.created_at >= since)
        return int((await self.session.execute(stmt)).scalar_one())

    async def check_budget(self, org_id: uuid.UUID) -> None:
        cap = await self.monthly_cap(org_id)
        if budget_exceeded(await self.spent(org_id, month_start()), cap):
            raise AppError(
                "ai_budget_exceeded", "this organization's monthly AI budget is used up", 402
            )

    async def record(
        self,
        org_id: uuid.UUID,
        *,
        project_id: uuid.UUID | None,
        run_id: uuid.UUID | None,
        model: str,
        task_class: str,
        usage: Usage,
    ) -> AiCostLedger:
        row = AiCostLedger(
            organization_id=org_id,
            project_id=project_id,
            run_id=run_id,
            model=model,
            task_class=task_class,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            cost_micro_usd=cost_micro_usd(model, usage, price_table(self.settings.ai_price_table)),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def page(
        self, org_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[AiCostLedger], int]:
        base = select(AiCostLedger).where(AiCostLedger.organization_id == org_id)
        total = (
            await self.session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        rows = (
            await self.session.execute(
                base.order_by(AiCostLedger.created_at.desc(), AiCostLedger.id)
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
        return list(rows), int(total)
