"""Remembers whether this database holds test or live payments (generated).

Test-mode and live-mode payments must never share a database: mixing them would make reports,
refunds and reconciliation wrong. The first start records the mode; a later start with the other
kind of key refuses to boot unless PAYMENTS_ALLOW_MODE_SWITCH=true for that one start.
"""

import structlog
from sqlalchemy.exc import IntegrityError

from app.db import session_factory
from app.payments import config
from app.payments.models import PaymentsLock

logger = structlog.get_logger()
_LOCK_ID = 1


class ModeMismatchError(RuntimeError):
    """The database was used with the other payments mode."""


def _name(livemode: bool) -> str:
    return "live" if livemode else "test"


async def ensure_payments_lock() -> None:
    settings = config.get_payments_settings()
    settings.check()
    livemode = settings.livemode
    async with session_factory() as session:
        for _ in range(2):
            row = await session.get(PaymentsLock, _LOCK_ID, with_for_update=True)
            if row is None:
                session.add(PaymentsLock(id=_LOCK_ID, provider=config.PROVIDER, livemode=livemode))
                try:
                    await session.commit()
                except IntegrityError:  # another process recorded it first: check theirs
                    await session.rollback()
                    continue
                return
            if (row.provider, row.livemode) == (config.PROVIDER, livemode):
                return
            if not settings.payments_allow_mode_switch:
                raise ModeMismatchError(
                    f"this database holds {row.provider} {_name(row.livemode)}-mode payments but "
                    f"this process is configured for {config.PROVIDER} {_name(livemode)} mode. "
                    "Use a separate database, or start once with PAYMENTS_ALLOW_MODE_SWITCH=true "
                    "if you really mean to switch."
                )
            logger.warning(
                "payments_mode_switched",
                before=f"{row.provider}/{_name(row.livemode)}",
                after=f"{config.PROVIDER}/{_name(livemode)}",
            )
            row.provider = config.PROVIDER
            row.livemode = livemode
            await session.commit()
            return
        raise RuntimeError("could not record the payments mode")
