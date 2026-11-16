"""Deletes old, finished auth rows (generated).

Every sign-in, rotation, code request and invitation leaves a row; once it is expired, used or
revoked for `retain_days` it can never be used again, so it is removed. Run it regularly
(daily is plenty), e.g. from cron: `python -m app.auth.purge [retain_days]`.
"""

import asyncio
import datetime as dt
import sys

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthInvitation, AuthRefreshToken, AuthSession, AuthVerificationCode
from app.db import session_factory

logger = structlog.get_logger()

DEFAULT_RETAIN_DAYS = 30  # well past any access token's lifetime, so no live token is affected


async def purge_expired(
    session: AsyncSession, *, retain_days: int = DEFAULT_RETAIN_DAYS, now: dt.datetime | None = None
) -> dict[str, int]:
    """Delete rows that ended more than `retain_days` ago. Returns the count per table."""
    cutoff = (now or dt.datetime.now(dt.UTC)) - dt.timedelta(days=retain_days)
    jobs = (
        (AuthRefreshToken, sa.or_(AuthRefreshToken.expires_at < cutoff, AuthRefreshToken.revoked_at < cutoff)),
        (
            AuthVerificationCode,
            sa.or_(AuthVerificationCode.expires_at < cutoff, AuthVerificationCode.consumed_at < cutoff),
        ),
        (AuthInvitation, sa.or_(AuthInvitation.expires_at < cutoff, AuthInvitation.accepted_at < cutoff)),
        (AuthSession, AuthSession.revoked_at < cutoff),
    )
    counts: dict[str, int] = {}
    for model, condition in jobs:
        result = await session.execute(sa.delete(model).where(condition))
        counts[model.__tablename__] = result.rowcount or 0
    await session.commit()
    logger.info("auth_purged", **counts)
    return counts


async def _main(retain_days: int) -> None:
    async with session_factory() as session:
        print(await purge_expired(session, retain_days=retain_days))  # noqa: T201


if __name__ == "__main__":
    asyncio.run(_main(int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_RETAIN_DAYS))
