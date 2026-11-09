"""Cost ledger writes/reads, per-org settings (BYO key) and the budget cap check."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.core import crypto
from app.exceptions import AppError
from app.models.ai_ledger import AiCostLedger, AiOrgSettings
from app.services.ai.base import Usage
from app.services.ai import platform_cap
from app.services.ai.pricing import cost_micro_usd, price_table

_HINT_MIN_KEY_LEN = 20  # a 4-char hint of a shorter key would reveal too large a share of it


def key_hint(key: str) -> str | None:
    return key[-4:] if len(key) >= _HINT_MIN_KEY_LEN else None


@dataclass(frozen=True)
class OrgReservation:
    org_id: uuid.UUID
    micro_usd: int
    id: uuid.UUID | None = None  # None when the org has no budget (nothing is held)


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
        approval_policy: dict[str, Any] | None = None,
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
            row.api_key_hint = key_hint(api_key)
        if clear_budget:
            row.monthly_budget_micro_usd = None
        if budget is not None:
            row.monthly_budget_micro_usd = budget
        if approval_policy is not None:  # B-001: replaces the override; {} clears it
            row.approval_policy = approval_policy or None
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

    # -- budget reservation (S2-009) ---------------------------------------------------------
    # Own short transactions on the bind, like PlatformCap: the organization row is locked, so
    # parallel callers are serialised, and the ledger row is written in the same transaction that
    # releases the hold, so a rolled-back request session can never lose it.

    def _maker(self) -> async_sessionmaker[AsyncSession]:
        bind = self.session.bind
        assert bind is not None
        return async_sessionmaker(bind, expire_on_commit=False)

    @staticmethod
    async def _lock_org(s: AsyncSession, org_id: uuid.UUID) -> None:
        # NO KEY UPDATE conflicts with itself but not with the FK checks other inserts take.
        await s.execute(
            text("SELECT id FROM organizations WHERE id = :o FOR NO KEY UPDATE"), {"o": org_id}
        )

    async def reserve_budget(self, org_id: uuid.UUID, need: int) -> OrgReservation:
        at = platform_cap.now()
        rid = uuid.uuid4()
        async with self._maker()() as s, s.begin():
            await self._lock_org(s, org_id)
            row = (
                await s.execute(
                    select(AiOrgSettings).where(AiOrgSettings.organization_id == org_id)
                )
            ).scalar_one_or_none()
            cap = (
                row.monthly_budget_micro_usd
                if row is not None and row.monthly_budget_micro_usd is not None
                else self.settings.ai_default_monthly_budget_micro_usd
            )
            if cap is None:
                return OrgReservation(org_id, need)
            await s.execute(
                text(
                    "DELETE FROM ai_spend_reservations"
                    " WHERE scope='org' AND organization_id=:o AND expires_at <= :now"
                ),
                {"o": org_id, "now": at},
            )
            spent = int(
                (
                    await s.execute(
                        select(func.coalesce(func.sum(AiCostLedger.cost_micro_usd), 0)).where(
                            AiCostLedger.organization_id == org_id,
                            AiCostLedger.created_at >= month_start(at),
                        )
                    )
                ).scalar_one()
            )
            held = int(
                (
                    await s.execute(
                        text(
                            "SELECT COALESCE(SUM(micro_usd), 0) FROM ai_spend_reservations"
                            " WHERE scope='org' AND organization_id=:o AND expires_at > :now"
                        ),
                        {"o": org_id, "now": at},
                    )
                ).scalar_one()
            )
            if spent + held + need <= cap:
                await s.execute(
                    text(
                        "INSERT INTO ai_spend_reservations (id, scope, organization_id, micro_usd, expires_at)"
                        " VALUES (:id, 'org', :o, :n, :exp)"
                    ),
                    {
                        "id": rid,
                        "o": org_id,
                        "n": need,
                        "exp": at + timedelta(seconds=self.settings.ai_reservation_ttl_seconds),
                    },
                )
                return OrgReservation(org_id, need, rid)
        raise AppError(
            "ai_budget_exceeded", "this organization's monthly AI budget is used up", 402
        )

    async def settle_budget(
        self,
        res: OrgReservation,
        *,
        project_id: uuid.UUID | None,
        run_id: uuid.UUID | None,
        model: str,
        task_class: str,
        usage: Usage | None,
        charge_worst_case: bool = False,
        step_key: str | None = None,
        after_settle: Callable[[AsyncSession], Awaitable[None]] | None = None,
    ) -> None:
        """Release the hold and write the ledger row in ONE transaction.

        usage given: the real cost. usage None + charge_worst_case: outcome unknown, so the worst
        case is recorded (zero tokens). usage None otherwise: the call never reached the model.

        step_key (B-009): a retried step carries the same key; a ledger row with that key is written
        once (the retry's row is skipped, under the org row lock). after_settle runs inside this same
        transaction with its session, so the caller's own write (the model step) commits or rolls
        back together with the ledger row.
        """
        async with self._maker()() as s, s.begin():
            await self._lock_org(s, res.org_id)
            if res.id is not None:
                await s.execute(
                    text("DELETE FROM ai_spend_reservations WHERE id=:id"), {"id": res.id}
                )
            if usage is not None:
                u = usage
                cost = cost_micro_usd(model, usage, price_table(self.settings.ai_price_table))
            elif charge_worst_case:
                u, cost = Usage(0, 0), res.micro_usd
            else:
                return
            dup = step_key is not None and (
                await s.execute(
                    select(AiCostLedger.id).where(AiCostLedger.step_key == step_key).limit(1)
                )
            ).first() is not None
            if not dup:
                s.add(
                    AiCostLedger(
                        step_key=step_key,
                        organization_id=res.org_id,
                        project_id=project_id,
                        run_id=run_id,
                        model=model,
                        task_class=task_class,
                        input_tokens=u.input_tokens,
                        output_tokens=u.output_tokens,
                        cache_read_tokens=u.cache_read_tokens,
                        cache_write_tokens=u.cache_write_tokens,
                        cost_micro_usd=cost,
                    )
                )
            if after_settle is not None:
                await s.flush()
                await after_settle(s)

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
