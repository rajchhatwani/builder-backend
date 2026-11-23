"""Compliance service (generated): legal holds, retention, consent, break-glass reads, de-identified export.

Rules that hold everywhere in this file:
  * rows are read and written through the entity models, so regulated mode (encrypted columns, blind indexes) keeps
    working: a purge or anonymise goes through the ORM, an export reads the decrypted value only to hash / drop it;
  * `compliance_audit.detail` holds ids, counts and slugs, never a field value (see `_clean`);
  * a row under an active legal hold is never purged or anonymised: holds are re-read per chunk under a per-entity
    advisory lock (placing a hold takes the same lock) and the DELETE itself carries a NOT EXISTS active-hold check;
    a purge also refuses a row whose cascading dependants are under a hold;
  * in a multi-tenant project holds, grants, audit rows and reads belong to the caller's tenant; an account with no
    tenant is refused (`require_tenant`)."""

import datetime as _dt
import functools
import hashlib
import hmac
import importlib
import math
import os
import re
import uuid as _uuid
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from fastapi.encoders import jsonable_encoder
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import effective_roles
from app.compliance import settings
from app.compliance.models import BreakGlassGrant, ComplianceAudit, Consent, LegalHold, RetentionRun
from app.core.errors import AppError, NotFoundError
from app.models._base import Base

CHUNK = 500
MAX_EXPORT_ROWS = 50_000
MAX_AUDIT_IDS = 100
SALT_ENV = "COMPLIANCE_EXPORT_SALT"
_SAFE_TEXT = re.compile(r"^[A-Za-z0-9_.:-]{1,40}$")


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


def _forbidden(message: str = "you do not have permission to do that") -> AppError:
    return AppError("forbidden", message, 403)


def model_for(entity: str) -> Any:
    cfg = settings.ENTITIES.get(entity)
    if cfg is None:
        raise AppError("unknown_entity", f"no entity named {entity!r}", 422)
    return getattr(importlib.import_module(cfg["module"]), cfg["class"])


# --- tenant + audit ----------------------------------------------------------------------------------------------


def require_tenant(user: Any) -> _uuid.UUID | None:
    """The caller's tenant in a multi-tenant project (an account without one is refused), else None."""
    if not settings.TENANT_SCOPED:
        return None
    tenant = getattr(user, "tenant_id", None)
    if tenant is None:
        raise _forbidden("this account belongs to no tenant")
    return tenant


def _clean(value: Any) -> Any:
    """Keep only what may sit in an audit row: numbers, booleans, ids, and short identifier-like text (a slug, an action
    code). Free text, which could be a field value, is dropped."""
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
    entity: str | None = None,
    record_id: _uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
    tenant: _uuid.UUID | None = None,
) -> None:
    session.add(
        ComplianceAudit(
            actor=actor, action=action, entity=entity, record_id=record_id, detail=_clean(detail or {}), tenant_id=tenant
        )
    )


async def lock_entities(session: AsyncSession, entities: Any) -> None:
    """Transaction-scoped advisory locks (sorted, so two callers cannot deadlock). Placing a hold and a retention chunk
    on the same entity serialise on them: a hold committed first is seen by the chunk, one placed later waits."""
    for entity in sorted(set(entities)):
        await session.execute(sa.text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"compliance:{entity}"})


# --- legal holds -------------------------------------------------------------------------------------------------


async def place_hold(
    session: AsyncSession, user: Any, entity: str, record_id: _uuid.UUID | None, reason: str
) -> LegalHold:
    tenant = require_tenant(user)
    model = model_for(entity)
    await lock_entities(session, [entity])
    if record_id is not None:
        found = await session.execute(
            sa.select(model.__table__.c["id"]).where(model.__table__.c["id"] == record_id, *_tenant_filter(model, user))
        )
        if found.first() is None:
            raise NotFoundError(f"no {entity} with that id")
    actor = str(user.id)
    hold = LegalHold(entity=entity, record_id=record_id, reason=reason, placed_by=actor, tenant_id=tenant)
    session.add(hold)
    await session.flush()
    audit(session, actor, "legal_hold.place", entity=entity, record_id=record_id, detail={"hold_id": hold.id}, tenant=tenant)
    await session.commit()
    return hold


async def list_holds(session: AsyncSession, user: Any, *, active_only: bool = True) -> list[LegalHold]:
    tenant = require_tenant(user)
    stmt = sa.select(LegalHold).order_by(LegalHold.placed_at, LegalHold.id)
    if active_only:
        stmt = stmt.where(LegalHold.released_at.is_(None))
    if tenant is not None:
        stmt = stmt.where(LegalHold.tenant_id == tenant)
    return list((await session.execute(stmt)).scalars())


async def release_hold(session: AsyncSession, user: Any, hold_id: _uuid.UUID) -> LegalHold:
    tenant = require_tenant(user)
    hold = await session.get(LegalHold, hold_id)
    if hold is None or (tenant is not None and hold.tenant_id != tenant):
        raise NotFoundError("no such legal hold")
    if hold.released_at is None:
        hold.released_at = _now()
        hold.released_by = str(user.id)
        audit(
            session, str(user.id), "legal_hold.release", entity=hold.entity, record_id=hold.record_id,
            detail={"hold_id": hold.id}, tenant=tenant,
        )
        await session.commit()
    return hold


# --- retention ---------------------------------------------------------------------------------------------------


def _cutoff(column: sa.Column[Any], days: int, now: _dt.datetime) -> Any:
    moment = now - _dt.timedelta(days=days)
    return moment if isinstance(column.type, sa.DateTime) else moment.date()


async def _active_holds(session: AsyncSession, entity: str) -> tuple[list[_uuid.UUID | None], set[_uuid.UUID]]:
    """(tenants of the whole-entity holds (None: not tenant scoped), ids under a record hold). Read fresh each call."""
    rows = (
        await session.execute(
            sa.select(LegalHold.record_id, LegalHold.tenant_id).where(
                LegalHold.entity == entity, LegalHold.released_at.is_(None)
            )
        )
    ).all()
    return [r[1] for r in rows if r[0] is None], {r[0] for r in rows if r[0] is not None}


def _whole_covers(whole: list[_uuid.UUID | None], row_tenant: _uuid.UUID | None, has_tenant: bool) -> bool:
    if not whole:
        return False
    return not has_tenant or any(t is None or t == row_tenant for t in whole)


@functools.cache
def _cascade_edges(table_name: str) -> tuple[tuple[str, str], ...]:
    """(dependant table, fk column) of every foreign key that deletes its rows when a row of `table_name` goes."""
    edges = []
    for dep in Base.metadata.tables.values():
        for fk in dep.foreign_keys:
            if fk.column.table.name == table_name and (fk.ondelete or "").upper() == "CASCADE":
                edges.append((dep.name, fk.parent.name))
    return tuple(sorted(edges))


def _entity_of_table(table_name: str) -> str | None:
    return next((n for n, c in settings.ENTITIES.items() if c["table"] == table_name), None)


def _cascade_entities(table_name: str, seen: set[str] | None = None) -> set[str]:
    seen = seen if seen is not None else set()
    for dep, _fk in _cascade_edges(table_name):
        if dep not in seen:
            seen.add(dep)
            _cascade_entities(dep, seen)
    return {e for e in (_entity_of_table(t) for t in seen) if e is not None}


async def _dependant_held(session: AsyncSession, table_name: str, ids: list[Any], depth: int = 0) -> bool:
    """True when a row that would be deleted along with `ids` (foreign keys with ON DELETE CASCADE) is under a hold."""
    for dep_name, fk_name in _cascade_edges(table_name):
        dep = Base.metadata.tables[dep_name]
        id_col = dep.c.get("id")
        if id_col is None:
            continue
        if depth > 6:
            return True  # too deep to be sure: refuse
        has_tenant = "tenant_id" in dep.c
        cols = [id_col, dep.c["tenant_id"]] if has_tenant else [id_col]
        rows = (await session.execute(sa.select(*cols).where(dep.c[fk_name].in_(ids)))).all()
        if not rows:
            continue
        entity = _entity_of_table(dep_name)
        if entity is not None:
            whole, held = await _active_holds(session, entity)
            if any(r[0] in held or _whole_covers(whole, r[1] if has_tenant else None, has_tenant) for r in rows):
                return True
        if await _dependant_held(session, dep_name, [r[0] for r in rows], depth + 1):
            return True
    return False


def _regulated_tokens() -> tuple[Any, Any] | None:
    try:
        return importlib.import_module("app.regulated.settings"), importlib.import_module("app.regulated.tokens")
    except ModuleNotFoundError:
        return None


def _tokenised(table_name: str, only: tuple[str, ...] | None = None) -> list[str]:
    reg = _regulated_tokens()
    if reg is None:
        return []
    rules = reg[0].PROTECTED.get(table_name, {})
    return [c for c, r in sorted(rules.items()) if r["mode"] == "tokenise" and (only is None or c in only)]


async def _vault_cleanup(session: AsyncSession, tokens: set[str]) -> None:
    """Delete the vault entry of every token that no tokenised column references any more (a token is shared by every
    row holding the same value, so one still in use stays)."""
    reg = _regulated_tokens()
    if reg is None or not tokens:
        return
    columns = [(t, c) for t, rules in reg[0].PROTECTED.items() for c, r in rules.items() if r["mode"] == "tokenise"]
    vault = sa.table(reg[1].VAULT_TABLE, sa.column("token", sa.Text()))
    for token in sorted(tokens):
        used = False
        for table_name, column in columns:
            ref = sa.table(table_name, sa.column(column, sa.Text()))
            if (await session.execute(sa.select(sa.literal(1)).select_from(ref).where(ref.c[column] == token).limit(1))).first():
                used = True
                break
        if not used:
            await session.execute(sa.delete(vault).where(vault.c.token == token))


async def _run_rule(session: AsyncSession, rule: dict[str, Any], now: _dt.datetime, dry_run: bool) -> dict[str, Any]:
    entity = rule["entity"]
    model = model_for(entity)
    table = model.__table__
    column = table.c[rule["date_field"]]
    purge = rule["action"] == "purge"
    fields: tuple[str, ...] = tuple(rule["anonymise_fields"])
    has_tenant = "tenant_id" in table.c
    stmt = sa.select(model).where(column < _cutoff(column, rule["days"], now))
    if not purge:
        stmt = stmt.where(sa.or_(*(table.c[f].is_not(None) for f in fields)))
    id_col = table.c["id"]
    token_cols = _tokenised(table.name, None if purge else fields)
    lock_on = sorted({entity, *(_cascade_entities(table.name) if purge else set())})
    hold_exists = sa.exists().where(
        LegalHold.released_at.is_(None),
        LegalHold.entity == entity,
        sa.or_(
            LegalHold.record_id == id_col,
            sa.and_(
                LegalHold.record_id.is_(None),
                *([sa.or_(LegalHold.tenant_id.is_(None), LegalHold.tenant_id == table.c["tenant_id"])] if has_tenant else []),
            ),
        ),
    )
    counts = {"matched": 0, "processed": 0, "held": 0, "blocked": 0}
    ids: list[str] = []
    held: list[str] = []
    last: _uuid.UUID | None = None
    while True:
        # one transaction per chunk: the locks (and the hold list read under them) are fresh for every chunk
        await lock_entities(session, lock_on)
        whole, held_ids = await _active_holds(session, entity)
        page = stmt.order_by(id_col).limit(CHUNK)
        if last is not None:
            page = page.where(id_col > last)
        rows = list((await session.execute(page)).scalars())
        if not rows:
            await session.commit()
            break
        last = rows[-1].id
        tokens: set[str] = set()
        for row in rows:
            row_id = row.id
            counts["matched"] += 1
            row_tenant = row.tenant_id if has_tenant else None
            is_held = row_id in held_ids or _whole_covers(whole, row_tenant, has_tenant)
            if not is_held and purge:
                is_held = await _dependant_held(session, table.name, [row_id])
            if is_held:
                counts["held"] += 1
                if len(held) < MAX_AUDIT_IDS:
                    held.append(str(row_id))
                continue
            if dry_run:
                counts["processed"] += 1
            else:
                seen = {v for c in token_cols if isinstance(v := getattr(row, c), str)}
                if purge:
                    try:
                        async with session.begin_nested():
                            result = await session.execute(sa.delete(table).where(id_col == row_id, ~hold_exists))
                        if result.rowcount == 0:  # a hold appeared since the chunk started: the statement refused
                            counts["held"] += 1
                            continue
                    except IntegrityError:  # something still references the row: it stays
                        counts["blocked"] += 1
                        continue
                else:
                    for name in fields:
                        cell = table.c[name]
                        setattr(row, name, None if cell.nullable else "")
                    await session.flush()
                tokens |= seen
                counts["processed"] += 1
            if len(ids) < MAX_AUDIT_IDS:
                ids.append(str(row_id))
        await _vault_cleanup(session, tokens)
        await session.commit()
        if not dry_run:
            session.expunge_all()
    return {"entity": entity, "action": rule["action"], **counts, "ids": ids, "held_ids": held}


async def run_retention(
    session: AsyncSession,
    actor: str,
    *,
    dry_run: bool = False,
    now: _dt.datetime | None = None,
    tenant: _uuid.UUID | None = None,
) -> dict[str, Any]:
    """Apply every retention rule. Rows under an active legal hold (or whose cascading dependants are) are skipped and
    counted as `held`. The run and each rule's outcome are audited (ids and counts only)."""
    moment = now or _now()
    results = []
    for rule in settings.RETENTION:
        results.append(await _run_rule(session, rule, moment, dry_run))
    summary = {
        "dry_run": dry_run,
        "rules": [{k: v for k, v in r.items() if k not in ("ids", "held_ids")} for r in results],
    }
    session.add(RetentionRun(actor=actor, dry_run=dry_run, summary=jsonable_encoder(summary)))
    for r in results:
        audit(
            session,
            actor,
            f"retention.{r['action']}" + (".dry_run" if dry_run else ""),
            entity=r["entity"],
            detail={k: r[k] for k in ("matched", "processed", "held", "blocked", "ids", "held_ids")},
            tenant=tenant,
        )
    await session.commit()
    return summary


# --- consent -----------------------------------------------------------------------------------------------------


def _purpose(purpose: str) -> str:
    if purpose not in settings.CONSENT_PURPOSES:
        raise AppError("unknown_purpose", f"{purpose!r} is not a declared purpose", 422)
    return purpose


def _active_consent(subject: str, purpose: str) -> Any:
    return sa.select(Consent).where(
        Consent.subject == subject, Consent.purpose == purpose, Consent.withdrawn_at.is_(None)
    )


async def grant_consent(session: AsyncSession, user: Any, subject: str, purpose: str) -> Consent:
    _purpose(purpose)
    tenant = require_tenant(user)
    existing = (await session.execute(_active_consent(subject, purpose))).scalars().first()
    if existing is not None:
        return existing
    consent = Consent(subject=subject, purpose=purpose, recorded_by=str(user.id))
    session.add(consent)
    await session.flush()
    audit(session, str(user.id), "consent.grant", detail={"consent_id": consent.id, "purpose": purpose}, tenant=tenant)
    await session.commit()
    return consent


async def withdraw_consent(session: AsyncSession, user: Any, subject: str, purpose: str) -> int:
    _purpose(purpose)
    tenant = require_tenant(user)
    rows = list((await session.execute(_active_consent(subject, purpose))).scalars())
    if not rows:
        raise NotFoundError("no active consent for that subject and purpose")
    for row in rows:
        row.withdrawn_at = _now()
    audit(
        session, str(user.id), "consent.withdraw", detail={"consent_ids": [r.id for r in rows], "purpose": purpose}, tenant=tenant
    )
    await session.commit()
    return len(rows)


async def has_consent(session: AsyncSession, subject: str, purpose: str) -> bool:
    _purpose(purpose)
    return (await session.execute(_active_consent(subject, purpose))).scalars().first() is not None


# --- break-glass -------------------------------------------------------------------------------------------------


def _bg_role(user: Any) -> str | None:
    held = effective_roles(user.roles)
    for role in settings.BREAK_GLASS["roles"]:
        if role in held:
            return str(role)
    return None


async def grant_break_glass(
    session: AsyncSession, user: Any, reason: str, entities: list[str], minutes: int
) -> BreakGlassGrant:
    cfg = settings.BREAK_GLASS
    actor = str(user.id)
    tenant = require_tenant(user)
    role = _bg_role(user) if cfg["enabled"] else None
    if role is None:
        audit(session, actor, "break_glass.denied", detail={"why": "role"}, tenant=tenant)
        await session.commit()
        raise _forbidden()
    if len(reason.strip()) < 10:
        raise AppError("validation_error", "a reason of at least 10 characters is required", 422)
    if not 1 <= minutes <= cfg["max_minutes"]:
        raise AppError("validation_error", f"minutes must be between 1 and {cfg['max_minutes']}", 422)
    if not entities:
        raise AppError("validation_error", "name at least one entity", 422)
    for entity in entities:
        model_for(entity)
    grant = BreakGlassGrant(
        user_id=user.id,
        role=role,
        reason=reason.strip(),
        entity_scope=sorted(set(entities)),
        expires_at=_now() + _dt.timedelta(minutes=minutes),
        tenant_id=tenant,
    )
    session.add(grant)
    await session.flush()
    audit(
        session,
        actor,
        "break_glass.grant",
        detail={"grant_id": grant.id, "entities": grant.entity_scope, "minutes": minutes, "role": role},
        tenant=tenant,
    )
    await session.commit()
    return grant


async def _deny(
    session: AsyncSession, actor: str, grant_id: _uuid.UUID, why: str, entity: str, tenant: _uuid.UUID | None
) -> AppError:
    audit(session, actor, "break_glass.denied", entity=entity, detail={"grant_id": grant_id, "why": why}, tenant=tenant)
    await session.commit()
    return _forbidden("this break-glass grant does not allow that")


def _row_dict(row: Any) -> dict[str, Any]:
    return {
        c.name: jsonable_encoder(getattr(row, c.key)) for c in row.__table__.columns if not c.name.endswith("_bidx")
    }


def _tenant_filter(model: Any, user: Any) -> list[Any]:
    tenant = require_tenant(user)
    column = model.__table__.c.get("tenant_id")
    return [column == tenant] if column is not None and tenant is not None else []


async def break_glass_read(
    session: AsyncSession, user: Any, grant_id: _uuid.UUID, entity: str, *, limit: int = 50, offset: int = 0
) -> list[dict[str, Any]]:
    """Rows of `entity`, bypassing the entity's own access rules, only while the caller's grant is active, unexpired and
    covers the entity. Every read, and every refusal, is audited (ids only)."""
    actor = str(user.id)
    tenant = require_tenant(user)
    grant = await session.get(BreakGlassGrant, grant_id)
    if grant is None or grant.user_id != user.id:
        raise await _deny(session, actor, grant_id, "grant", entity, tenant)
    if tenant is not None and grant.tenant_id != tenant:
        raise await _deny(session, actor, grant_id, "tenant", entity, tenant)
    if grant.revoked_at is not None:
        raise await _deny(session, actor, grant_id, "revoked", entity, tenant)
    if grant.expires_at <= _now():
        raise await _deny(session, actor, grant_id, "expired", entity, tenant)
    if entity not in grant.entity_scope:
        raise await _deny(session, actor, grant_id, "scope", entity, tenant)
    if not settings.BREAK_GLASS["enabled"] or _bg_role(user) is None:
        raise await _deny(session, actor, grant_id, "role", entity, tenant)
    model = model_for(entity)
    stmt = sa.select(model).where(*_tenant_filter(model, user)).order_by(model.__table__.c["id"])
    rows = list((await session.execute(stmt.limit(max(1, min(limit, 200))).offset(max(0, offset)))).scalars())
    audit(
        session,
        actor,
        "break_glass.read",
        entity=entity,
        detail={"grant_id": grant_id, "count": len(rows), "ids": [str(r.id) for r in rows]},
        tenant=tenant,
    )
    await session.commit()
    return [_row_dict(r) for r in rows]


async def revoke_break_glass(session: AsyncSession, user: Any, grant_id: _uuid.UUID, *, is_admin: bool) -> BreakGlassGrant:
    tenant = require_tenant(user)
    grant = await session.get(BreakGlassGrant, grant_id)
    if grant is None or (tenant is not None and grant.tenant_id != tenant):
        raise NotFoundError("no such grant")
    if grant.user_id != user.id and not is_admin:
        raise _forbidden()
    if grant.revoked_at is None:
        grant.revoked_at = _now()
        audit(session, str(user.id), "break_glass.revoke", detail={"grant_id": grant.id}, tenant=tenant)
        await session.commit()
    return grant


async def list_grants(session: AsyncSession, user: Any) -> list[BreakGlassGrant]:
    tenant = require_tenant(user)
    stmt = sa.select(BreakGlassGrant).order_by(BreakGlassGrant.granted_at)
    if tenant is not None:
        stmt = stmt.where(BreakGlassGrant.tenant_id == tenant)
    return list((await session.execute(stmt)).scalars())


async def list_audit(session: AsyncSession, user: Any, *, limit: int = 100, action: str | None = None) -> list[ComplianceAudit]:
    tenant = require_tenant(user)
    stmt = sa.select(ComplianceAudit).order_by(ComplianceAudit.at.desc(), ComplianceAudit.id).limit(max(1, min(limit, 500)))
    if action:
        stmt = stmt.where(ComplianceAudit.action == action)
    if tenant is not None:
        stmt = stmt.where(ComplianceAudit.tenant_id == tenant)
    return list((await session.execute(stmt)).scalars())


# --- de-identified export ----------------------------------------------------------------------------------------


def _salt() -> bytes:
    value = os.environ.get(SALT_ENV, "")
    if len(value) < 16:
        raise AppError("export_salt_missing", f"set {SALT_ENV} (at least 16 characters) before exporting", 503)
    return value.encode()


def pseudonym(salt: bytes, entity: str, row_id: Any) -> str:
    return hmac.new(salt, f"id:{entity}:{row_id}".encode(), hashlib.sha256).hexdigest()[:32]


def hash_value(salt: bytes, entity: str, field: str, value: Any) -> str | None:
    """HMAC-SHA256 under the project's export salt: never a plain hash, so it cannot be brute-forced without the salt."""
    if value is None:
        return None
    return hmac.new(salt, f"{entity}.{field}:{value}".encode(), hashlib.sha256).hexdigest()


def generalise(value: Any) -> Any:
    """dates -> year, numbers -> bucket of 10, strings -> first character; anything else is dropped."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, _dt.date):
        return value.year
    if isinstance(value, int | float | Decimal):
        return int(math.floor(float(value) / 10) * 10)
    if isinstance(value, str):
        return value[:1]
    return None


def treat(salt: bytes, entity: str, field: str, treatment: str, value: Any) -> Any:
    if field in settings.PROTECTED.get(entity, ()) and treatment not in ("hash", "drop"):
        return None  # a protected field is never exported in the clear
    if treatment == "hash":
        return hash_value(salt, entity, field, value)
    if treatment == "generalise":
        return generalise(value)
    if treatment == "keep":
        return jsonable_encoder(value)
    return None


async def export_entity(session: AsyncSession, user: Any, entity: str) -> dict[str, Any]:
    cfg = settings.EXPORT_ENTITIES.get(entity)
    if cfg is None:
        raise AppError("unknown_entity", f"{entity!r} is not exportable", 422)
    salt = _salt()
    model = model_for(entity)
    table = model.__table__
    treatments = {f: t for f, t in settings.EXPORT_FIELDS.get(entity, {}).items() if t != "drop"}  # unlisted: dropped
    purpose = settings.EXPORT_CONSENT_PURPOSE
    consented: set[str] | None = None
    if purpose is not None:
        consented = {
            r[0]
            for r in (
                await session.execute(
                    sa.select(Consent.subject).where(Consent.purpose == purpose, Consent.withdrawn_at.is_(None))
                )
            ).all()
        }
    subject_field = cfg["subject_field"]
    where = _tenant_filter(model, user)
    out: list[dict[str, Any]] = []
    skipped = 0
    truncated = False
    last: Any = None
    while not truncated:
        page = sa.select(model).where(*where).order_by(table.c["id"]).limit(CHUNK)
        if last is not None:
            page = page.where(table.c["id"] > last)
        rows = list((await session.execute(page)).scalars())
        if not rows:
            break
        last = rows[-1].id
        for row in rows:
            if consented is not None:
                subject = getattr(row, subject_field) if subject_field else None
                if subject is None or str(subject) not in consented:
                    skipped += 1
                    continue
            if len(out) >= MAX_EXPORT_ROWS:
                truncated = True
                break
            item: dict[str, Any] = {"pseudonym": pseudonym(salt, entity, row.id)}
            for field, treatment in treatments.items():
                item[field] = treat(salt, entity, field, treatment, getattr(row, field))
            out.append(item)
    audit(
        session,
        str(user.id),
        "export.run",
        entity=entity,
        detail={"rows": len(out), "skipped_no_consent": skipped, "truncated": truncated},
        tenant=require_tenant(user),
    )
    await session.commit()
    return {"entity": entity, "rows": out, "skipped_no_consent": skipped, "truncated": truncated}
