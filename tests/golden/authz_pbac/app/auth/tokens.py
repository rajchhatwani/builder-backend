"""Where refresh tokens live: the database.

The service only talks to the `TokenStore` interface. A refresh token is single use: redeeming
it ("rotating") marks it revoked and the caller issues a replacement in the same family. If a
token that was already rotated is presented again, the whole family is revoked, because only
a thief holding an old copy can do that.
"""

import datetime as dt
import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthRefreshToken


@dataclass(frozen=True)
class Rotation:
    # "ok", "unknown" (never issued or expired), "expired" or "reused" (family revoked)
    status: str
    user_id: uuid.UUID | None = None
    family_id: uuid.UUID | None = None


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class TokenStore:
    """Refresh tokens in the `auth_refresh_tokens` table, inside the caller's transaction.

    Methods do not commit, except where a revocation must survive the request failing."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self, user_id: uuid.UUID, family_id: uuid.UUID, token_hash: str, expires_at: dt.datetime
    ) -> None:
        self.session.add(
            AuthRefreshToken(
                user_id=user_id, family_id=family_id, token_hash=token_hash, expires_at=expires_at
            )
        )

    async def rotate(self, token_hash: str) -> Rotation:
        stmt = (
            sa.select(AuthRefreshToken)
            .where(AuthRefreshToken.token_hash == token_hash)
            .with_for_update()
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return Rotation("unknown")
        if row.revoked_at is not None:
            await self.revoke_family(row.family_id)
            await self.session.commit()
            return Rotation("reused")
        if row.expires_at <= _now():
            return Rotation("expired")
        row.revoked_at = _now()
        return Rotation("ok", row.user_id, row.family_id)

    async def revoke_family_of(self, token_hash: str) -> uuid.UUID | None:
        stmt = sa.select(AuthRefreshToken.family_id).where(
            AuthRefreshToken.token_hash == token_hash
        )
        family_id = (await self.session.execute(stmt)).scalar_one_or_none()
        if family_id is not None:
            await self.revoke_family(family_id)
        return family_id

    async def revoke_family(self, family_id: uuid.UUID) -> None:
        await self.session.execute(
            sa.update(AuthRefreshToken)
            .where(AuthRefreshToken.family_id == family_id, AuthRefreshToken.revoked_at.is_(None))
            .values(revoked_at=_now())
        )

    async def revoke_all(self, user_id: uuid.UUID) -> None:
        await self.session.execute(
            sa.update(AuthRefreshToken)
            .where(AuthRefreshToken.user_id == user_id, AuthRefreshToken.revoked_at.is_(None))
            .values(revoked_at=_now())
        )
