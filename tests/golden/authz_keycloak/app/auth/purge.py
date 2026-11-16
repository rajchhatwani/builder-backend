"""Deletes old, ended sign-in records (generated).

Every Keycloak session id seen leaves an `auth_sessions` row; once revoked for `retain_days` it
can be removed. Run it regularly (daily is plenty): `python -m app.auth.purge [retain_days]`.
"""

import asyncio
import datetime as dt
import sys

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthSession
from app.db import session_factory

logger = structlog.get_logger()

DEFAULT_RETAIN_DAYS = 30  # well past any access token's lifetime, so no live token is affected


async def purge_expired(
    session: AsyncSession, *, retain_days: int = DEFAULT_RETAIN_DAYS, now: dt.datetime | None = None
) -> dict[str, int]:
    """Delete sessions revoked more than `retain_days` ago. Returns the count per table."""
    cutoff = (now or dt.datetime.now(dt.UTC)) - dt.timedelta(days=retain_days)
    result = await session.execute(sa.delete(AuthSession).where(AuthSession.revoked_at < cutoff))
    await session.commit()
    counts = {AuthSession.__tablename__: result.rowcount or 0}
    logger.info("auth_purged", **counts)
    return counts


async def _main(retain_days: int) -> None:
    async with session_factory() as session:
        print(await purge_expired(session, retain_days=retain_days))  # noqa: T201


if __name__ == "__main__":
    asyncio.run(_main(int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_RETAIN_DAYS))
