"""Platform-wide hard spend cap: reserve the worst case BEFORE a call, settle after.

The counter lives in one global row updated with atomic SQL, in its own short transactions (so a
rolled-back request never loses spend and parallel callers cannot both slip under the cap).
Fake providers are never counted.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.exceptions import AppError
from app.services.ai.base import CompletionRequest, Usage
from app.services.ai.pricing import cost_micro_usd, price_table

_CHARS_PER_TOKEN = 3  # conservative: real text is ~4 chars/token, so this over-estimates input


def now() -> datetime:
    """The clock for reservation expiry (module-level so tests can advance it)."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class Reservation:
    micro_usd: int
    id: uuid.UUID | None = None


def worst_case_micro_usd(model: str, request: CompletionRequest, settings: Settings) -> int:
    """Estimated input tokens at the dearest input rate + max_tokens at the output rate."""
    prices = price_table(settings.ai_price_table)
    blob = json.dumps(
        {
            "s": request.system,
            "m": [(m.role, m.content) for m in request.messages],
            "t": [(t.name, t.description, t.input_schema) for t in request.tools],
        },
        default=str,
    )
    est_in = (
        len(blob) // _CHARS_PER_TOKEN + 1 + (1500 if request.tools else 0)
    )  # hidden tool-use prompt
    p = prices[model]
    in_rate = max(p.get("input", 0), p.get("cache_write", 0))
    return -(-(est_in * in_rate + request.max_tokens * p.get("output", 0)) // 1_000_000)


class PlatformCap:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        bind = session.bind
        assert bind is not None
        self._maker = async_sessionmaker(bind, expire_on_commit=False)
        self.settings = settings

    async def _ensure_row(self, s: AsyncSession) -> None:
        await s.execute(
            text("INSERT INTO ai_platform_budget (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
        )

    async def _cap(self, s: AsyncSession) -> int | None:
        await self._ensure_row(s)
        cap = self.settings.ai_platform_cap_micro_usd
        override = (
            await s.execute(
                text("SELECT cap_override_micro_usd FROM ai_platform_budget WHERE id=1")
            )
        ).scalar_one_or_none()
        if override is not None:
            cap = override if cap is None else min(cap, override)
        return cap

    async def _reap(self, s: AsyncSession, at: datetime) -> int:
        """Delete expired reservations (any scope) and give the platform ones back to the counter.

        Deleting first and decrementing by what the DELETE returned means two concurrent reapers can
        never both give back the same row (the loser sees it gone).
        """
        rows = (
            await s.execute(
                text(
                    "DELETE FROM ai_spend_reservations WHERE expires_at <= :now RETURNING scope, micro_usd"
                ),
                {"now": at},
            )
        ).all()
        freed = sum(int(r[1]) for r in rows if r[0] == "platform")
        if freed:
            await s.execute(
                text(
                    "UPDATE ai_platform_budget SET reserved_micro_usd = GREATEST(reserved_micro_usd - :f, 0),"
                    " updated_at = now() WHERE id=1"
                ),
                {"f": freed},
            )
        return freed

    async def reap_expired(self, at: datetime | None = None) -> int:
        """Free reservations whose TTL has passed (crash recovery). Returns micro-USD given back."""
        async with self._maker() as s, s.begin():
            await self._ensure_row(s)
            return await self._reap(s, at or now())

    async def reserve(self, model: str, request: CompletionRequest) -> Reservation:
        need = worst_case_micro_usd(model, request, self.settings)
        at = now()
        rid = uuid.uuid4()
        async with self._maker() as s, s.begin():
            cap = await self._cap(s)  # also guarantees the singleton row exists
            await self._reap(s, at)  # lazy sweep: a dead process's hold never outlives its TTL
            if cap is None:
                got = (
                    await s.execute(
                        text(
                            "UPDATE ai_platform_budget SET reserved_micro_usd = reserved_micro_usd + :n"
                            " WHERE id=1 RETURNING id"
                        ),
                        {"n": need},
                    )
                ).first()
            else:
                got = (
                    await s.execute(
                        text(
                            "UPDATE ai_platform_budget SET reserved_micro_usd = reserved_micro_usd + :n,"
                            " updated_at = now() WHERE id=1 AND spent_micro_usd + reserved_micro_usd + :n <= :cap"
                            " RETURNING id"
                        ),
                        {"n": need, "cap": cap},
                    )
                ).first()
            if got is not None:
                await s.execute(
                    text(
                        "INSERT INTO ai_spend_reservations (id, scope, micro_usd, expires_at)"
                        " VALUES (:id, 'platform', :n, :exp)"
                    ),
                    {
                        "id": rid,
                        "n": need,
                        "exp": at + timedelta(seconds=self.settings.ai_reservation_ttl_seconds),
                    },
                )
        if got is None:
            raise AppError(
                "ai_platform_cap",
                "the platform's total AI spending limit would be exceeded by this call",
                402,
            )
        return Reservation(need, rid)

    async def _release(self, s: AsyncSession, res: Reservation, spend: int) -> None:
        """Drop the reservation row; only give the hold back if it was still ours (not reaped)."""
        held = 0
        if res.id is not None:
            row = (
                await s.execute(
                    text("DELETE FROM ai_spend_reservations WHERE id=:id RETURNING micro_usd"),
                    {"id": res.id},
                )
            ).first()
            held = int(row[0]) if row else 0
        await s.execute(
            text(
                "UPDATE ai_platform_budget SET reserved_micro_usd = GREATEST(reserved_micro_usd - :r, 0),"
                " spent_micro_usd = spent_micro_usd + :a, updated_at = now() WHERE id=1"
            ),
            {"r": held, "a": spend},
        )

    async def settle(self, res: Reservation, model: str, usage: Usage | None) -> None:
        """Replace the reservation by the actual cost (or by 0 when the call failed unsent)."""
        actual = (
            cost_micro_usd(model, usage, price_table(self.settings.ai_price_table)) if usage else 0
        )
        async with self._maker() as s, s.begin():
            await self._release(s, res, actual)

    async def settle_worst_case(self, res: Reservation) -> None:
        async with self._maker() as s, s.begin():
            await self._release(s, res, res.micro_usd)

    async def status(self) -> dict[str, int | None]:
        async with self._maker() as s, s.begin():
            await self._ensure_row(s)
            await self._reap(s, now())
            row = (
                await s.execute(
                    text(
                        "SELECT spent_micro_usd, reserved_micro_usd FROM ai_platform_budget WHERE id=1"
                    )
                )
            ).one()
            cap = await self._cap(s)
        return {"cap": cap, "spent": int(row[0]), "reserved": int(row[1])}
