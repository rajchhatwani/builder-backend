"""Remembers which identity provider this database belongs to (generated).

Users, and the data they own, are tied to one identity source: built-in accounts or one
Keycloak realm. Starting a build that uses a different source on the same database would
orphan those users or, worse, hand their data to whoever signs up next, so the app refuses
to start instead. Set AUTH_ALLOW_PROVIDER_SWITCH=true for the one start that is meant to
switch, then remove it.
"""

import structlog
from sqlalchemy.exc import IntegrityError

from app.auth import config
from app.auth.models import AuthProviderLock
from app.db import session_factory

logger = structlog.get_logger()

_LOCK_ID = 1


class ProviderMismatchError(RuntimeError):
    """The database was last used with a different identity provider."""


def _describe(provider: str, realm: str | None) -> str:
    return provider if realm is None else f"{provider} (realm {realm})"


async def ensure_provider_lock() -> None:
    """Record the provider on first start; refuse to start if it later differs."""
    settings = config.get_auth_settings()
    async with session_factory() as session:
        for _ in range(2):
            row = await session.get(AuthProviderLock, _LOCK_ID, with_for_update=True)
            if row is None:
                session.add(
                    AuthProviderLock(
                        id=_LOCK_ID, provider=config.PROVIDER, realm=config.PROVIDER_REALM
                    )
                )
                try:
                    await session.commit()
                except IntegrityError:  # another worker recorded it first: check theirs
                    await session.rollback()
                    continue
                return
            if (row.provider, row.realm) == (config.PROVIDER, config.PROVIDER_REALM):
                return
            before = _describe(row.provider, row.realm)
            after = _describe(config.PROVIDER, config.PROVIDER_REALM)
            if not settings.auth_allow_provider_switch:
                raise ProviderMismatchError(
                    f"this database was used with {before} but this build uses {after}. "
                    "Users would not carry over. To switch on purpose, start once with "
                    "AUTH_ALLOW_PROVIDER_SWITCH=true."
                )
            logger.warning("auth_provider_switched", before=before, after=after)
            row.provider = config.PROVIDER
            row.realm = config.PROVIDER_REALM
            await session.commit()
            return
        raise RuntimeError("could not record the auth provider")
