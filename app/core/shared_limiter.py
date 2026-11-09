"""Fixed-window limiter backed by the database, so every worker sees the same count (FX-1).

`hit()` is atomic (INSERT .. ON CONFLICT DO UPDATE .. RETURNING), uses the database clock, and
prunes the key's expired windows on the way; `prune()` sweeps the rest. Callers keep their cheap
in-process limiter as a FIRST check and call this second, so a flood is mostly refused without a
query. If the database cannot be reached the request is refused (fail closed, 503): every path
that uses this needs the database next anyway.

Fixed windows allow up to 2x the limit across a window boundary; that is accepted for abuse
limits (the per-account lockout and the platform spend cap are the hard controls).
"""

import time
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.exceptions import AppError

_HIT = text(
    """
    WITH t AS (SELECT floor(extract(epoch FROM clock_timestamp()))::bigint AS now)
    INSERT INTO rate_windows AS r (key, window_start, hits, expires_at)
    SELECT :k, (t.now / CAST(:w AS bigint)) * CAST(:w AS bigint), 1,
           (t.now / CAST(:w AS bigint) + 1) * CAST(:w AS bigint)
    FROM t
    ON CONFLICT (key, window_start) DO UPDATE SET hits = r.hits + 1
    RETURNING hits, expires_at - floor(extract(epoch FROM clock_timestamp()))::bigint
    """
)
_PRUNE_KEY = text(
    "DELETE FROM rate_windows WHERE key = :k "
    "AND expires_at <= floor(extract(epoch FROM clock_timestamp()))::bigint"
)
_PRUNE_ALL = text(
    "DELETE FROM rate_windows WHERE expires_at <= floor(extract(epoch FROM clock_timestamp()))::bigint"
)
PRUNE_EVERY_SECONDS = 300.0


class SharedLimiter:
    def __init__(self, factory: Callable[[], async_sessionmaker[AsyncSession]]) -> None:
        self._factory = factory  # called per use, so a test can swap the factory
        self._last_prune = 0.0

    async def hit(
        self,
        key: str,
        limit: int,
        window_seconds: int,
        factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> int | None:
        """Count one attempt. None = allowed; else seconds until the window ends."""
        if len(key) > 200:
            raise ValueError("limiter key too long")
        try:
            async with (factory or self._factory())() as s:
                await s.execute(_PRUNE_KEY, {"k": key})
                row = (await s.execute(_HIT, {"k": key, "w": window_seconds})).one()
                await s.commit()
                await self._maybe_prune(s)
        except Exception:
            raise AppError("rate_limiter_unavailable", "try again shortly", 503) from None
        hits, remaining = int(row[0]), int(row[1])
        return None if hits <= limit else max(1, remaining)

    async def _maybe_prune(self, s: AsyncSession) -> None:
        now = time.monotonic()
        if now - self._last_prune < PRUNE_EVERY_SECONDS:
            return
        self._last_prune = now
        await s.execute(_PRUNE_ALL)
        await s.commit()

    async def prune(self) -> None:
        async with self._factory()() as s:
            await s.execute(_PRUNE_ALL)
            await s.commit()

    async def reset(self, key: str | None = None) -> None:
        """Test/ops helper: forget one key (or all)."""
        async with self._factory()() as s:
            if key is None:
                await s.execute(text("DELETE FROM rate_windows"))
            else:
                await s.execute(text("DELETE FROM rate_windows WHERE key = :k"), {"k": key})
            await s.commit()
