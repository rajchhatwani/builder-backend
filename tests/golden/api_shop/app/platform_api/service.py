"""API platform service (generated): keys, apps, rate limits, audit.

Rules that hold everywhere in this file:
  * a key is `bbk_<s|p>_<prefix8>_<secret>`; only its sha256 hash and the prefix are stored, the plaintext is returned
    once at creation, lookup is by prefix and the hash is compared in constant time;
  * `platform_audit.detail` holds ids and slugs, never a key or a field value (see `_clean`);
  * everything an administrator does is scoped to the caller's tenant (an account with no tenant is refused);
  * the rate limit is a fixed window per key kept in the database, so it holds across workers."""

import datetime as _dt
import hashlib
import hmac
import re
import secrets
import uuid as _uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, NotFoundError
from app.db import session_factory
from app.platform_api import events, settings
from app.platform_api.models import ApiKey, PlatformAudit

KEY_PREFIX = "bbk"
_SAFE_TEXT = re.compile(r"^[A-Za-z0-9_.:-]{1,40}$")
_LIMIT = re.compile(r"^(\d+)/(\d+)?(second|minute|hour|day)s?$")
_UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
MAX_PAGE = 200


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


def parse_limit(text: str) -> tuple[int, int]:
    """'60/minute' -> (60, 60); '100/5minutes' -> (100, 300): (requests, window seconds)."""
    match = _LIMIT.match(text)
    if match is None:
        raise ValueError(f"not a rate limit: {text!r}")
    return int(match.group(1)), int(match.group(2) or 1) * _UNITS[match.group(3)]


def limit_for(row: Any) -> tuple[int, int]:
    return parse_limit(settings.SANDBOX_RATE_LIMIT if row.environment == "sandbox" else settings.RATE_LIMIT)


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def new_key(environment: str) -> tuple[str, str, str]:
    """(plaintext, prefix, hash). The prefix is hex so it never contains the separator."""
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(24)[:32]
    plaintext = f"{KEY_PREFIX}_{'s' if environment == 'sandbox' else 'p'}_{prefix}_{secret}"
    return plaintext, prefix, hash_key(plaintext)


def parse_key(plaintext: str) -> tuple[str, str] | None:
    """(environment letter, prefix) of a well formed key, else None."""
    parts = plaintext.split("_", 3)
    if len(parts) != 4 or parts[0] != KEY_PREFIX or parts[1] not in ("s", "p") or len(parts[2]) != 8 or len(parts[3]) < 16:
        return None
    return parts[1], parts[2]


# --- tenant + audit ----------------------------------------------------------------------------------------------


def _forbidden(message: str = "you do not have permission to do that") -> AppError:
    return AppError("forbidden", message, 403)


def require_tenant(user: Any) -> _uuid.UUID | None:
    """The caller's tenant in a multi-tenant project (an account without one is refused), else None."""
    if not settings.TENANT_SCOPED:
        return None
    tenant = getattr(user, "tenant_id", None)
    if tenant is None:
        raise _forbidden("this account belongs to no tenant")
    return tenant


def _tenant_is(column: Any, tenant: _uuid.UUID | None) -> Any:
    return column.is_(None) if tenant is None else column == tenant


def _clean(value: Any) -> Any:
    """Keep only what may sit in an audit row: numbers, booleans, ids and short identifier-like text. Free text, which
    could be a key or a field value, is dropped."""
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, _uuid.UUID):
        return str(value)
    if isinstance(value, str):
        return value if _SAFE_TEXT.match(value) else None
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    return None


def audit(
    session: AsyncSession,
    actor: str,
    action: str,
    *,
    target: str | None = None,
    detail: dict[str, Any] | None = None,
    tenant: _uuid.UUID | None = None,
) -> None:
    session.add(PlatformAudit(actor=actor, action=action, target=target, detail=_clean(detail or {}), tenant_id=tenant))


async def audit_denial(key: ApiKey, reason: str, **detail: Any) -> None:
    """A refused public call, written in its own transaction (the request itself is being refused)."""
    async with session_factory() as session:
        audit(
            session,
            f"key:{key.id}",
            "public.denied",
            target=str(key.id),
            detail={"reason": reason, **detail},
            tenant=key.tenant_id,
        )
        await session.commit()


# --- key views ---------------------------------------------------------------------------------------------------


def key_status(row: Any, now: _dt.datetime | None = None) -> str:
    if row.revoked_at is not None:
        return "revoked"
    return "expired" if row.expires_at <= (now or _now()) else "active"


def key_view(row: ApiKey) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "prefix": row.prefix,
        "kind": row.kind,
        "app": row.app,
        "environment": row.environment,
        "scopes": list(row.scopes),
        "created_at": row.created_at,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "last_used_at": row.last_used_at,
        "status": key_status(row),
    }


def catalogue() -> dict[str, Any]:
    return {
        "entities": [
            {"entity": name, "plural_path": cfg["plural_path"], "fields": list(cfg["fields"]), "sandbox": cfg["sandbox"]}
            for name, cfg in sorted(settings.ENTITIES.items())
        ],
        "rate_limit": settings.RATE_LIMIT,
        "sandbox_rate_limit": settings.SANDBOX_RATE_LIMIT,
        "key_ttl_days": settings.KEY_TTL_DAYS,
    }


# --- keys (administration) ---------------------------------------------------------------------------------------


def _check_scopes(scopes: list[str], environment: str) -> list[str]:
    ordered = list(dict.fromkeys(scopes))
    if not ordered:
        raise AppError("validation_error", "name at least one entity", 422)
    for scope in ordered:
        cfg = settings.ENTITIES.get(scope)
        if cfg is None:
            raise AppError("unknown_scope", f"{scope!r} is not a public entity", 422)
        if environment == "sandbox" and not cfg["sandbox"]:
            raise AppError("sandbox_scope", f"{scope!r} is not available to sandbox keys", 422)
    return ordered


async def _store_key(
    session: AsyncSession, user: Any, tenant: _uuid.UUID | None, *, kind: str, name: str, environment: str,
    scopes: list[str], ttl_days: int, app: str | None = None, events: tuple[str, ...] = (),
) -> tuple[ApiKey, str]:
    for _ in range(5):  # an 8 hex prefix collision is possible in principle: draw again
        plaintext, prefix, digest = new_key(environment)
        taken = (await session.execute(sa.select(ApiKey.id).where(ApiKey.prefix == prefix))).first()
        if taken is None:
            break
    else:  # pragma: no cover
        raise AppError("internal_error", "could not issue a key", 500)
    row = ApiKey(
        kind=kind, name=name, prefix=prefix, key_hash=digest, environment=environment, scopes=scopes, app=app,
        event_types=list(events), tenant_id=tenant, created_by=str(user.id), expires_at=_now() + _dt.timedelta(days=ttl_days),
    )
    session.add(row)
    await session.flush()
    return row, plaintext


async def create_key(
    session: AsyncSession, user: Any, name: str, scopes: list[str], environment: str, ttl_days: int | None
) -> tuple[ApiKey, str]:
    tenant = require_tenant(user)
    checked = _check_scopes(scopes, environment)
    row, plaintext = await _store_key(
        session, user, tenant, kind="key", name=name, environment=environment, scopes=checked,
        ttl_days=ttl_days or settings.KEY_TTL_DAYS,
    )
    audit(session, str(user.id), "key.create", target=str(row.id), detail={"environment": environment, "scopes": checked}, tenant=tenant)
    await session.commit()
    return row, plaintext


async def list_keys(session: AsyncSession, user: Any) -> list[ApiKey]:
    tenant = require_tenant(user)
    stmt = sa.select(ApiKey).where(_tenant_is(ApiKey.tenant_id, tenant)).order_by(ApiKey.created_at.desc(), ApiKey.id)
    return list((await session.execute(stmt)).scalars())


async def revoke_key(session: AsyncSession, user: Any, key_id: _uuid.UUID) -> ApiKey:
    tenant = require_tenant(user)
    row = (
        await session.execute(
            sa.select(ApiKey).where(ApiKey.id == key_id, _tenant_is(ApiKey.tenant_id, tenant)).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("no such key")
    if row.revoked_at is None:
        row.revoked_at = _now()
        row.revoked_by = str(user.id)
        audit(session, str(user.id), "key.revoke", target=str(row.id), detail={"kind": row.kind, "app": row.app}, tenant=tenant)
    await session.commit()
    return row


# --- apps --------------------------------------------------------------------------------------------------------


async def _active_installs(session: AsyncSession, tenant: _uuid.UUID | None, app: str | None = None) -> list[ApiKey]:
    stmt = sa.select(ApiKey).where(
        ApiKey.kind == "app", ApiKey.revoked_at.is_(None), ApiKey.expires_at > _now(), _tenant_is(ApiKey.tenant_id, tenant)
    )
    if app is not None:
        stmt = stmt.where(ApiKey.app == app)
    return list((await session.execute(stmt.order_by(ApiKey.created_at.desc()))).scalars())


async def list_apps(session: AsyncSession, user: Any) -> list[dict[str, Any]]:
    tenant = require_tenant(user)
    installs = {row.app: row for row in reversed(await _active_installs(session, tenant))}
    out = []
    for name, cfg in sorted(settings.APPS.items()):
        inst = installs.get(name)
        out.append(
            {
                "name": name,
                "title": cfg["title"],
                "scopes": list(cfg["scopes"]),
                "events": list(cfg["events"]),
                "installed": inst is not None,
                "installation_id": inst.id if inst else None,
                "granted_scopes": list(inst.scopes) if inst else [],
                "installed_at": inst.created_at if inst else None,
            }
        )
    return out


async def install_app(
    session: AsyncSession, user: Any, name: str, scopes: list[str] | None
) -> tuple[ApiKey, str]:
    tenant = require_tenant(user)
    cfg = settings.APPS.get(name)
    if cfg is None:
        raise NotFoundError("no such app")
    events.require_signing_key()  # before anything is stored: an install must be able to hand out its signing secret
    granted = list(cfg["scopes"]) if scopes is None else list(dict.fromkeys(scopes))
    if not granted:
        raise AppError("validation_error", "grant at least one scope", 422)
    for scope in granted:
        if scope not in cfg["scopes"]:
            raise AppError("scope_not_offered", f"app {name!r} does not ask for {scope!r}", 422)
    await session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"platform_app:{tenant}:{name}"}
    )
    if await _active_installs(session, tenant, name):
        raise ConflictError(f"app {name!r} is already installed")
    row, token = await _store_key(
        session, user, tenant, kind="app", name=name, environment="prod", scopes=granted,
        ttl_days=settings.KEY_TTL_DAYS, app=name, events=tuple(cfg["events"]),
    )
    audit(session, str(user.id), "app.install", target=str(row.id), detail={"app": name, "scopes": granted}, tenant=tenant)
    await session.commit()
    return row, token


async def uninstall_app(session: AsyncSession, user: Any, name: str) -> ApiKey:
    tenant = require_tenant(user)
    installs = await _active_installs(session, tenant, name) if name in settings.APPS else []
    if not installs:
        raise NotFoundError("that app is not installed")
    now = _now()
    for row in installs:
        row.revoked_at = now
        row.revoked_by = str(user.id)
        audit(session, str(user.id), "app.uninstall", target=str(row.id), detail={"app": name}, tenant=tenant)
    await session.commit()
    return installs[0]


async def list_audit(session: AsyncSession, user: Any, limit: int, offset: int) -> list[PlatformAudit]:
    tenant = require_tenant(user)
    stmt = (
        sa.select(PlatformAudit)
        .where(_tenant_is(PlatformAudit.tenant_id, tenant))
        .order_by(PlatformAudit.at.desc(), PlatformAudit.id)
        .limit(min(limit, MAX_PAGE))
        .offset(offset)
    )
    return list((await session.execute(stmt)).scalars())


# --- public API: key lookup + rate limit -------------------------------------------------------------------------


async def authenticate_key(plaintext: str) -> ApiKey | None:
    """The key row for a well formed, known key (matching hash), else None. Status is judged by the caller."""
    parsed = parse_key(plaintext)
    if parsed is None:
        return None
    letter, prefix = parsed
    async with session_factory() as session:
        row = (await session.execute(sa.select(ApiKey).where(ApiKey.prefix == prefix))).scalar_one_or_none()
    if row is None or not hmac.compare_digest(row.key_hash, hash_key(plaintext)):
        return None
    if (letter == "s") != (row.environment == "sandbox"):
        return None
    return row


async def hit_limit(row: ApiKey) -> tuple[int, int, int]:
    """Count one call in the key's current fixed window: (count, limit, seconds until the window ends). Written in its
    own transaction so a refused call still counts."""
    limit, period = limit_for(row)
    now = _now()
    epoch = int(now.timestamp())
    start = _dt.datetime.fromtimestamp(epoch // period * period, _dt.UTC)
    async with session_factory() as session:
        count = (
            await session.execute(
                sa.text(
                    "INSERT INTO api_key_usage (key_id, window_start, count) VALUES (:k, :w, 1) "
                    "ON CONFLICT (key_id, window_start) DO UPDATE SET count = api_key_usage.count + 1 RETURNING count"
                ),
                {"k": row.id, "w": start},
            )
        ).scalar_one()
        await session.execute(sa.update(ApiKey).where(ApiKey.id == row.id).values(last_used_at=now))
        if count == 1:  # first call of a window: drop windows nobody can need any more
            await session.execute(
                sa.text("DELETE FROM api_key_usage WHERE window_start < :old"), {"old": now - _dt.timedelta(days=1)}
            )
        await session.commit()
    return int(count), limit, max(1, epoch // period * period + period - epoch)
