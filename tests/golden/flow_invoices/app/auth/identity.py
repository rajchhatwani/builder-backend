"""Who a caller is: local user ids are kept apart from identity-provider subjects (generated).

`auth_users.id` is owned by this app and never changes. A token only says "issuer X calls this
person Y"; `auth_identities` maps that pair to the local id. Replace the identity provider and
every user, `created_by_id` and tenant row stays where it is.

Your own code should take a `Principal` (`from app.auth.deps import CurrentPrincipal`), never
read `claims["sub"]` itself: the subject is not a user id.
"""

import dataclasses
import datetime as dt
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Literal

import sqlalchemy as sa
import structlog
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthIdentity, AuthSession

logger = structlog.get_logger()

_NAMESPACE = uuid.UUID("6f1b3f0e-5a0e-4c7e-9a43-0c2a1c1a9d10")
_SEEN_EVERY = dt.timedelta(minutes=5)
MAX_SUBJECT = 255


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@dataclasses.dataclass(frozen=True)
class Principal:
    """The signed-in caller, as hooks and custom code see them."""

    user_id: uuid.UUID
    issuer: str
    subject: str
    tenant_id: uuid.UUID | None
    tenant_external_ref: str | None
    roles: tuple[str, ...]
    session_id: str | None
    auth_time: int | None


@dataclasses.dataclass(frozen=True)
class LinkDecision:
    """What to do with an identity this app has not seen: create a user, link it to an existing
    one, or refuse it."""

    action: Literal["create", "link", "reject"]
    user_id: uuid.UUID | None = None  # for "link"
    reason: str = ""


# --- hook points (default: do nothing special; failures refuse the sign-in) ---------------


async def default_resolve_identity(claims: dict[str, Any]) -> LinkDecision:
    """Never links to an existing user by e-mail address: an unverified address proves nothing."""
    return LinkDecision("create")


async def default_on_user_provisioned(principal: Principal) -> None:
    return None


async def default_on_session_ended(session_id: str, reason: str) -> None:
    return None


@dataclasses.dataclass
class Hooks:
    """Replace a field to change a decision. Failure policy is fail_closed."""

    resolve_identity: Callable[[dict[str, Any]], Awaitable[LinkDecision]] = default_resolve_identity
    on_user_provisioned: Callable[[Principal], Awaitable[None]] = default_on_user_provisioned
    on_session_ended: Callable[[str, str], Awaitable[None]] = default_on_session_ended


HOOKS = Hooks()


# --- identities --------------------------------------------------------------------------


def subject_is_valid(subject: object) -> bool:
    """Any non-empty text up to 255 characters, without control characters (OIDC allows no more)."""
    return (
        isinstance(subject, str)
        and 0 < len(subject) <= MAX_SUBJECT
        and subject.isprintable()
    )


def new_user_id(issuer: str, subject: str) -> uuid.UUID:
    """The local id for a user seen for the first time. A subject that is a UUID keeps it (so
    existing data lines up); anything else gets a stable id derived from issuer and subject.
    Callers must check the id is free (`user_id_is_free`) before using the first form."""
    try:
        return uuid.UUID(subject)
    except ValueError:
        return derived_user_id(issuer, subject)


def derived_user_id(issuer: str, subject: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"{issuer}\n{subject}")


async def find_user_id(session: AsyncSession, issuer: str, subject: str) -> uuid.UUID | None:
    stmt = sa.select(AuthIdentity.user_id).where(
        AuthIdentity.issuer == issuer, AuthIdentity.subject == subject
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def add_identity(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    issuer: str,
    subject: str,
    provider: str,
    email: str | None,
    email_verified: bool,
) -> None:
    """Link an identity to a user. Linking the same pair twice is not an error; linking a pair
    that already belongs to someone else is left alone (the existing link wins)."""
    await session.execute(
        insert(AuthIdentity)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            issuer=issuer,
            subject=subject,
            provider=provider,
            email_at_link=email,
            email_verified=email_verified,
            created_at=_now(),
        )
        .on_conflict_do_nothing(index_elements=["issuer", "subject"])
    )


async def note_seen(session: AsyncSession, issuer: str, subject: str) -> None:
    """Record activity at most every few minutes, so reads stay reads."""
    cutoff = _now() - _SEEN_EVERY
    result = await session.execute(
        sa.update(AuthIdentity)
        .where(
            AuthIdentity.issuer == issuer,
            AuthIdentity.subject == subject,
            sa.or_(AuthIdentity.last_seen_at.is_(None), AuthIdentity.last_seen_at < cutoff),
        )
        .values(last_seen_at=_now())
    )
    if result.rowcount:  # type: ignore[attr-defined]
        await session.commit()


async def relink_issuer(session: AsyncSession, old: str, new: str) -> int:
    """Move every identity from one issuer to another (same subjects): the identity provider
    moved or was renamed. Local user ids do not change. Returns how many were moved."""
    clash = await session.execute(
        sa.select(sa.func.count())
        .select_from(AuthIdentity)
        .where(AuthIdentity.issuer == new)
    )
    if clash.scalar_one():
        raise ValueError(f"identities already exist for {new}; refusing to merge")
    result = await session.execute(
        sa.update(AuthIdentity).where(AuthIdentity.issuer == old).values(issuer=new)
    )
    await session.execute(sa.update(AuthSession).where(AuthSession.issuer == old).values(issuer=new))
    await session.commit()
    return int(result.rowcount)  # type: ignore[attr-defined]


# --- sessions ----------------------------------------------------------------------------


async def open_session(session: AsyncSession, user_id: uuid.UUID, issuer: str, sid: str) -> bool:
    """Record a sign-in the first time it is seen; False means it was already ended and must be
    refused. One indexed read for a session we know."""
    sid = sid[:MAX_SUBJECT]
    known = (
        await session.execute(
            sa.select(AuthSession.revoked_at).where(
                AuthSession.issuer == issuer, AuthSession.sid == sid
            )
        )
    ).first()
    if known is not None:
        return known[0] is None
    await session.execute(
        insert(AuthSession)
        .values(id=uuid.uuid4(), user_id=user_id, sid=sid, issuer=issuer, created_at=_now())
        .on_conflict_do_nothing(index_elements=["issuer", "sid"])
    )
    await session.commit()
    return await session_is_live(session, issuer, sid)


async def session_is_live(session: AsyncSession, issuer: str, sid: str) -> bool:
    """False only for a session that was explicitly ended; an unknown one is not refused."""
    revoked = (
        await session.execute(
            sa.select(AuthSession.revoked_at).where(
                AuthSession.issuer == issuer, AuthSession.sid == sid[:MAX_SUBJECT]
            )
        )
    ).scalar_one_or_none()
    return revoked is None


async def end_session(session: AsyncSession, issuer: str, sid: str, reason: str) -> int:
    result = await session.execute(
        sa.update(AuthSession)
        .where(
            AuthSession.issuer == issuer,
            AuthSession.sid == sid[:MAX_SUBJECT],
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
    )
    await session.commit()
    ended = int(result.rowcount)  # type: ignore[attr-defined]
    if ended:
        await _announce_end(sid, reason)
    return ended


async def end_sessions_of_user(
    session: AsyncSession, user_id: uuid.UUID, reason: str, *, issuer: str | None = None
) -> int:
    """End every live session of a user (optionally only those of one issuer)."""
    stmt = sa.select(AuthSession.sid).where(
        AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
    )
    if issuer is not None:
        stmt = stmt.where(AuthSession.issuer == issuer)
    sids = list((await session.execute(stmt)).scalars())
    if not sids:
        return 0
    update = sa.update(AuthSession).where(
        AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
    )
    if issuer is not None:
        update = update.where(AuthSession.issuer == issuer)
    await session.execute(update.values(revoked_at=_now()))
    await session.commit()
    for sid in sids:
        await _announce_end(sid, reason)
    return len(sids)


async def _announce_end(sid: str, reason: str) -> None:
    try:
        await HOOKS.on_session_ended(sid, reason)
    except Exception as exc:  # the session is already ended: report, never undo
        logger.error("on_session_ended_failed", error=type(exc).__name__)
