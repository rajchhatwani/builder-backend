"""Platform-wide hard spend cap: reserve the worst case BEFORE a call, settle after.

The counter lives in one global row updated with atomic SQL, in its own short transactions (so a
rolled-back request never loses spend and parallel callers cannot both slip under the cap).
Fake providers are never counted.
"""

import json
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.exceptions import AppError
from app.services.ai.base import CompletionRequest, Usage
from app.services.ai.pricing import cost_micro_usd, price_table

_CHARS_PER_TOKEN = 3  # conservative: real text is ~4 chars/token, so this over-estimates input


@dataclass(frozen=True)
class Reservation:
    micro_usd: int


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
    est_in = len(blob) // _CHARS_PER_TOKEN + 1 + (1500 if request.tools else 0)  # hidden tool-use prompt
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
        await s.execute(text("INSERT INTO ai_platform_budget (id) VALUES (1) ON CONFLICT (id) DO NOTHING"))

    async def _cap(self, s: AsyncSession) -> int | None:
        await self._ensure_row(s)
        cap = self.settings.ai_platform_cap_micro_usd
        override = (
            await s.execute(text("SELECT cap_override_micro_usd FROM ai_platform_budget WHERE id=1"))
        ).scalar_one_or_none()
        if override is not None:
            cap = override if cap is None else min(cap, override)
        return cap

    async def reserve(self, model: str, request: CompletionRequest) -> Reservation:
        need = worst_case_micro_usd(model, request, self.settings)
        async with self._maker() as s, s.begin():
            cap = await self._cap(s)
            if cap is None:
                await s.execute(
                    text("UPDATE ai_platform_budget SET reserved_micro_usd = reserved_micro_usd + :n WHERE id=1"),
                    {"n": need},
                )
                return Reservation(need)
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
        if got is None:
            raise AppError(
                "ai_platform_cap",
                "the platform's total AI spending limit would be exceeded by this call",
                402,
            )
        return Reservation(need)

    async def settle(self, res: Reservation, model: str, usage: Usage | None) -> None:
        """Replace the reservation by the actual cost (or by 0 when the call failed unsent)."""
        actual = cost_micro_usd(model, usage, price_table(self.settings.ai_price_table)) if usage else 0
        async with self._maker() as s, s.begin():
            await s.execute(
                text(
                    "UPDATE ai_platform_budget SET reserved_micro_usd = GREATEST(reserved_micro_usd - :r, 0),"
                    " spent_micro_usd = spent_micro_usd + :a, updated_at = now() WHERE id=1"
                ),
                {"r": res.micro_usd, "a": actual},
            )

    async def settle_worst_case(self, res: Reservation) -> None:
        async with self._maker() as s, s.begin():
            await s.execute(
                text(
                    "UPDATE ai_platform_budget SET reserved_micro_usd = GREATEST(reserved_micro_usd - :r, 0),"
                    " spent_micro_usd = spent_micro_usd + :r, updated_at = now() WHERE id=1"
                ),
                {"r": res.micro_usd},
            )

    async def status(self) -> dict[str, int | None]:
        async with self._maker() as s, s.begin():
            await self._ensure_row(s)
            row = (
                await s.execute(
                    text("SELECT spent_micro_usd, reserved_micro_usd FROM ai_platform_budget WHERE id=1")
                )
            ).one()
            cap = await self._cap(s)
        return {"cap": cap, "spent": int(row[0]), "reserved": int(row[1])}


