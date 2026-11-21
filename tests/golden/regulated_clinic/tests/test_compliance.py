"""Compliance (generated): retention + legal hold, consent, break-glass and de-identified export, on the real database.

The tests read the project's own settings (app/compliance/settings.py), so they follow whatever the spec declares and
skip a section the spec does not use. Rows are built straight through the entity models."""

import asyncio
import datetime as dt
import hashlib
import json
import os
import random
import string
import subprocess
import sys
import types
import uuid
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from app.auth.models import AuthUser
from app.compliance import service, settings
from app.compliance.models import LegalHold
from app.core.errors import AppError
from app.db import session_factory
from app.models._base import Base
from tests._auth_support import ALL_ROLES, authed_client, client_for, outbox, sign_in  # noqa: F401

ADMIN_EMAIL = "all-roles@example.com"
IDENTIFIER_FRAGMENTS = ("email", "phone", "name", "ssn", "passport", "address", "dob")
BG = settings.BREAK_GLASS


@pytest.fixture(autouse=True)
def _export_salt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPLIANCE_EXPORT_SALT", "export-salt-" + "x" * 24)


# --- helpers (not tests) -----------------------------------------------------------------------------------------


def _model_of_table(table: str) -> Any:
    for mapper in Base.registry.mappers:
        if mapper.local_table.name == table:
            return mapper.class_
    raise LookupError(table)


def _token(length: int = 10) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=length))


def _marker() -> str:
    return "Zq" + uuid.uuid4().hex[:8]


async def _fill(session: Any, column: sa.Column[Any], tenant: uuid.UUID | None) -> Any:
    if column.foreign_keys:
        target = next(iter(column.foreign_keys)).column
        parent = await _make(session, _model_of_table(target.table.name), tenant)
        return getattr(parent, target.name)
    kind = column.type.impl if isinstance(column.type, sa.types.TypeDecorator) else column.type
    if isinstance(kind, sa.Enum):
        return kind.enums[0]
    if isinstance(kind, sa.Uuid):
        return uuid.uuid4()
    if isinstance(kind, sa.Boolean):
        return False
    if isinstance(kind, sa.DateTime):
        return dt.datetime.now(dt.UTC)
    if isinstance(kind, sa.Date):
        return dt.date.today()
    if isinstance(kind, sa.Float):
        return 1.0
    if isinstance(kind, sa.Numeric):
        return Decimal("1")
    if isinstance(kind, sa.Integer):
        return 1
    if isinstance(kind, sa.JSON):
        return {}
    return _token(min(getattr(kind, "length", None) or 10, 10))


async def _make(session: Any, model: Any, tenant: uuid.UUID | None, **values: Any) -> Any:
    """Insert one row with every required column filled (parents are created on demand)."""
    data: dict[str, Any] = dict(values)
    for column in model.__table__.columns:
        if column.name in data or column.primary_key:
            continue
        if column.name == "tenant_id" and tenant is not None:
            data["tenant_id"] = tenant
        elif not (column.nullable or column.default is not None or column.server_default is not None):
            data[column.name] = await _fill(session, column, tenant)
    row = model(**data)
    session.add(row)
    await session.flush()
    return row


def _when(column: sa.Column[Any], days: int) -> Any:
    moment = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    return moment if isinstance(column.type, sa.DateTime) else moment.date()


async def _expired(rule: dict[str, Any], tenant: uuid.UUID | None, **extra: Any) -> uuid.UUID:
    """A row older than the rule's retention (with something to clear when the rule anonymises)."""
    model = service.model_for(rule["entity"])
    values: dict[str, Any] = {rule["date_field"]: _when(model.__table__.c[rule["date_field"]], rule["days"] + 2)}
    async with session_factory() as session:
        for name in rule["anonymise_fields"]:
            values[name] = await _fill(session, model.__table__.c[name], tenant)
        values.update(extra)
        row = await _make(session, model, tenant, **values)
        await session.commit()
        return row.id


async def _fresh(rule: dict[str, Any], tenant: uuid.UUID | None, **extra: Any) -> uuid.UUID:
    model = service.model_for(rule["entity"])
    async with session_factory() as session:
        values = {name: await _fill(session, model.__table__.c[name], tenant) for name in rule["anonymise_fields"]}
        values.update(extra)
        row = await _make(session, model, tenant, **values)
        await session.commit()
        return row.id


async def _state(rule: dict[str, Any], row_id: uuid.UUID) -> str:
    """gone | cleared (every anonymise field empty) | kept."""
    async with session_factory() as session:
        row = await session.get(service.model_for(rule["entity"]), row_id)
    if row is None:
        return "gone"
    fields = rule["anonymise_fields"]
    if rule["action"] == "anonymise" and fields and all(getattr(row, f) in (None, "") for f in fields):
        return "cleared"
    return "kept"


def _done(rule: dict[str, Any]) -> str:
    return "gone" if rule["action"] == "purge" else "cleared"


async def _run(client: AsyncClient, *, dry_run: bool = False) -> dict[str, Any]:
    response = await client.post("/compliance/retention/run", json={"dry_run": dry_run})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _summary(body: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
    return next(r for r in body["rules"] if r["entity"] == rule["entity"] and r["action"] == rule["action"])


async def _tenant(authed: AsyncClient, email: str = ADMIN_EMAIL) -> uuid.UUID | None:  # noqa: ARG001
    column = getattr(AuthUser, "tenant_id", None)
    if column is None:
        return None
    async with session_factory() as session:
        value = (await session.execute(sa.select(column).where(AuthUser.email == email))).scalar_one()
        return value


async def _audit(action: str) -> list[Any]:
    async with session_factory() as session:
        rows = (await session.execute(sa.text("SELECT detail, entity, record_id FROM compliance_audit WHERE action = :a ORDER BY at, id"), {"a": action})).all()
    return list(rows)


def _need(condition: bool, why: str) -> None:
    if not condition:
        pytest.skip(why)


# --- retention + legal hold --------------------------------------------------------------------------------------


async def test_retention_purges_expired_rows(authed_client: AsyncClient) -> None:  # noqa: F811
    _need(bool(settings.RETENTION), "the spec has no retention rule")
    tenant = await _tenant(authed_client)
    for rule in settings.RETENTION:
        old, fresh = await _expired(rule, tenant), await _fresh(rule, tenant)
        dry = await _expired(rule, tenant)
        body = await _run(authed_client, dry_run=True)  # a dry run changes nothing
        assert body["dry_run"] is True and _summary(body, rule)["processed"] >= 2
        assert await _state(rule, old) == "kept" and await _state(rule, dry) == "kept"
        body = await _run(authed_client)
        assert _summary(body, rule)["processed"] >= 2
        assert await _state(rule, old) == _done(rule) and await _state(rule, dry) == _done(rule)
        assert await _state(rule, fresh) == "kept"
        assert await _state(rule, old) == _done(rule)
        later = await _expired(rule, tenant)  # the documented scheduler command does the same
        done = subprocess.run(
            [sys.executable, "-m", "app.compliance.purge"], env=dict(os.environ), capture_output=True, text=True, timeout=300
        )
        assert done.returncode == 0, done.stdout + done.stderr
        assert await _state(rule, later) == _done(rule)
    for action in ("retention.purge", "retention.anonymise"):
        for detail, _entity, _record in await _audit(action):
            text = json.dumps(detail)
            assert set(detail) <= {"matched", "processed", "held", "blocked", "ids", "held_ids"}
            assert "Zq" not in text
    for rule in settings.RETENTION:
        assert await _audit(f"retention.{rule['action']}")
        assert await _audit(f"retention.{rule['action']}.dry_run")
    async with session_factory() as session:
        runs = (await session.execute(sa.text("SELECT count(*) FROM retention_runs"))).scalar_one()
    assert runs >= 3


async def test_purge_refuses_rows_under_legal_hold(authed_client: AsyncClient) -> None:  # noqa: F811
    _need(bool(settings.RETENTION), "the spec has no retention rule")
    rule = settings.RETENTION[0]
    tenant = await _tenant(authed_client)
    held, free = await _expired(rule, tenant), await _expired(rule, tenant)
    placed = await authed_client.post(
        "/compliance/legal-holds", json={"entity": rule["entity"], "record_id": str(held), "reason": "litigation hold"}
    )
    assert placed.status_code == 201, placed.text
    assert (await authed_client.post("/compliance/legal-holds", json={"entity": "Nope", "reason": "x" * 5})).status_code == 422
    body = await _run(authed_client)
    assert await _state(rule, held) == "kept"  # refused
    assert await _state(rule, free) == _done(rule)
    assert _summary(body, rule)["held"] >= 1
    audits = await _audit(f"retention.{rule['action']}")
    assert any(str(held) in json.dumps(detail) for detail, _e, _r in audits)  # the audit names the held id

    whole = await authed_client.post("/compliance/legal-holds", json={"entity": rule["entity"], "reason": "regulator inquiry"})
    assert whole.status_code == 201 and whole.json()["record_id"] is None
    extra = await _expired(rule, tenant)
    body = await _run(authed_client)
    assert await _state(rule, extra) == "kept" and await _state(rule, held) == "kept"  # a whole-entity hold covers every row
    assert _summary(body, rule)["held"] >= 2 and _summary(body, rule)["processed"] == 0
    listed = (await authed_client.get("/compliance/legal-holds")).json()
    assert {h["id"] for h in listed} >= {placed.json()["id"], whole.json()["id"]}

    async with client_for({}) as http:  # default deny: a user without the compliance roles gets nothing
        nobody = await sign_in(http, "nobody-holds@example.com", roles=[])
        for call in (http.get("/compliance/legal-holds", headers=nobody), http.post("/compliance/retention/run", json={}, headers=nobody)):
            assert (await call).status_code == 403
        assert (await http.get("/compliance/legal-holds")).status_code == 401


async def test_legal_hold_release_allows_purge(authed_client: AsyncClient) -> None:  # noqa: F811
    _need(bool(settings.RETENTION), "the spec has no retention rule")
    rule = settings.RETENTION[0]
    tenant = await _tenant(authed_client)
    row = await _expired(rule, tenant)
    hold = (
        await authed_client.post(
            "/compliance/legal-holds", json={"entity": rule["entity"], "record_id": str(row), "reason": "audit in progress"}
        )
    ).json()
    await _run(authed_client)
    assert await _state(rule, row) == "kept"
    released = await authed_client.delete(f"/compliance/legal-holds/{hold['id']}")
    assert released.status_code == 200 and released.json()["released_at"] is not None
    assert hold["id"] not in {h["id"] for h in (await authed_client.get("/compliance/legal-holds")).json()}
    assert (await authed_client.delete(f"/compliance/legal-holds/{uuid.uuid4()}")).status_code == 404
    await _run(authed_client)
    assert await _state(rule, row) == _done(rule)
    assert await _audit("legal_hold.release")


# --- consent -----------------------------------------------------------------------------------------------------


async def test_consent_grant_and_withdraw(authed_client: AsyncClient) -> None:  # noqa: F811
    _need(bool(settings.CONSENT_PURPOSES), "the spec declares no consent purpose")
    purpose = settings.CONSENT_PURPOSES[0]
    subject = "subject-" + _token(6)
    check = {"subject": subject, "purpose": purpose}
    assert (await authed_client.get("/compliance/consents/check", params=check)).json()["granted"] is False
    granted = await authed_client.post("/compliance/consents", json=check)
    assert granted.status_code == 201 and granted.json()["withdrawn_at"] is None
    again = await authed_client.post("/compliance/consents", json=check)
    assert again.json()["id"] == granted.json()["id"]  # granting twice does not stack
    assert (await authed_client.get("/compliance/consents/check", params=check)).json()["granted"] is True
    assert (await authed_client.post("/compliance/consents", json={"subject": subject, "purpose": "not-a-purpose"})).status_code == 422
    withdrawn = await authed_client.post("/compliance/consents/withdraw", json=check)
    assert withdrawn.status_code == 200 and withdrawn.json() == {"withdrawn": 1}
    assert (await authed_client.get("/compliance/consents/check", params=check)).json()["granted"] is False
    assert (await authed_client.post("/compliance/consents/withdraw", json=check)).status_code == 404
    regranted = await authed_client.post("/compliance/consents", json=check)  # a new grant after a withdrawal
    assert regranted.json()["id"] != granted.json()["id"]
    for action in ("consent.grant", "consent.withdraw"):
        for detail, _entity, _record in await _audit(action):
            assert subject not in json.dumps(detail)  # the subject is not copied into the audit log


# --- break-glass -------------------------------------------------------------------------------------------------


def _bg_entity() -> str:
    return settings.RETENTION[0]["entity"] if settings.RETENTION else next(iter(settings.ENTITIES))


async def _bg_row(authed: AsyncClient) -> tuple[str, uuid.UUID, dict[str, str]]:
    entity = _bg_entity()
    model = service.model_for(entity)
    markers: dict[str, str] = {}
    values: dict[str, Any] = {}
    for column in model.__table__.columns:
        kind = column.type.impl if isinstance(column.type, sa.types.TypeDecorator) else column.type
        if isinstance(kind, sa.String | sa.Text) and not column.foreign_keys and not column.primary_key:
            if column.name in settings.PROTECTED.get(entity, ()) or any(f in column.name.lower() for f in IDENTIFIER_FRAGMENTS):
                values[column.name] = markers[column.name] = _marker()
    async with session_factory() as session:
        row = await _make(session, model, await _tenant(authed), **values)
        await session.commit()
        return entity, row.id, markers


async def test_break_glass_is_audited_and_time_boxed(authed_client: AsyncClient) -> None:  # noqa: F811
    _need(bool(BG["enabled"]), "the spec has no break-glass")
    entity, row_id, markers = await _bg_row(authed_client)
    too_long = await authed_client.post(
        "/compliance/break-glass", json={"reason": "emergency access needed", "entities": [entity], "minutes": BG["max_minutes"] + 1}
    )
    assert too_long.status_code == 422  # never longer than max_minutes
    short = await authed_client.post("/compliance/break-glass", json={"reason": "short", "entities": [entity], "minutes": 5})
    assert short.status_code == 422  # a real reason is required
    made = await authed_client.post(
        "/compliance/break-glass", json={"reason": "patient is unconscious, need history", "entities": [entity], "minutes": 5}
    )
    assert made.status_code == 201, made.text
    grant = made.json()
    window = dt.datetime.fromisoformat(grant["expires_at"]) - dt.datetime.fromisoformat(grant["granted_at"])
    assert dt.timedelta(minutes=4) < window <= dt.timedelta(minutes=5, seconds=5)  # time-boxed to the minutes asked
    assert grant["role"] in BG["roles"] and grant["entity_scope"] == [entity]

    read = await authed_client.get(f"/compliance/break-glass/{grant['id']}/records/{entity}")
    assert read.status_code == 200, read.text
    rows = read.json()
    assert str(row_id) in {r["id"] for r in rows}
    mine = next(r for r in rows if r["id"] == str(row_id))
    for name, marker in markers.items():
        # the emergency reader sees the real value (decrypted by the model layer); a tokenised field shows its token
        assert mine[name] == marker or (isinstance(mine[name], str) and mine[name].startswith("tok_"))
    audits = await _audit("break_glass.read")
    assert audits and any(str(row_id) in json.dumps(detail) for detail, _e, _r in audits)
    for detail, audited_entity, _record in audits:
        assert audited_entity == entity
        assert not any(m in json.dumps(detail) for m in markers.values())  # ids only, never a value
    assert await _audit("break_glass.grant")

    revoked = await authed_client.post(f"/compliance/break-glass/{grant['id']}/revoke")
    assert revoked.status_code == 200 and revoked.json()["revoked_at"] is not None
    assert (await authed_client.get(f"/compliance/break-glass/{grant['id']}/records/{entity}")).status_code == 403


async def test_break_glass_denied_without_role_or_after_expiry(authed_client: AsyncClient) -> None:  # noqa: F811
    _need(bool(BG["enabled"]), "the spec has no break-glass")
    entity, _row_id, _markers = await _bg_row(authed_client)
    body = {"reason": "urgent clinical need", "entities": [entity], "minutes": 5}
    async with client_for({}) as http:
        nobody = await sign_in(http, "nobody-bg@example.com", roles=[])
        assert (await http.post("/compliance/break-glass", json=body, headers=nobody)).status_code == 403  # no role
        assert (await http.post("/compliance/break-glass", json=body)).status_code == 401
        grant = (await authed_client.post("/compliance/break-glass", json=body)).json()
        url = f"/compliance/break-glass/{grant['id']}/records/{entity}"
        assert (await http.get(url, headers=nobody)).status_code == 403  # somebody else's grant
        assert (await http.get(url)).status_code == 401
        assert (await http.post(f"/compliance/break-glass/{grant['id']}/revoke", headers=nobody)).status_code in (403, 404)
    assert (await authed_client.get(url)).status_code == 200
    other = [e for e in settings.ENTITIES if e != entity]
    if other:
        assert (await authed_client.get(f"/compliance/break-glass/{grant['id']}/records/{other[0]}")).status_code == 403  # not in scope

    async with session_factory() as session:  # the grant runs out
        await session.execute(
            sa.text("UPDATE break_glass_grants SET expires_at = :t WHERE id = :i"),
            {"t": dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1), "i": uuid.UUID(grant["id"])},
        )
        await session.commit()
    assert (await authed_client.get(url)).status_code == 403
    assert (await authed_client.get(f"/compliance/break-glass/{uuid.uuid4()}/records/{entity}")).status_code == 403
    denied = await _audit("break_glass.denied")
    assert denied and all(not detail.get("ids") for detail, _e, _r in denied)


# --- de-identified export ----------------------------------------------------------------------------------------


def _export_entity() -> str:
    return next(iter(settings.EXPORT_ENTITIES))


async def _export_row(authed: AsyncClient, entity: str, subject_consent: str | None) -> tuple[Any, dict[str, str]]:
    """A row of `entity` whose identifier columns hold unique markers; grants consent to its subject when asked."""
    model = service.model_for(entity)
    markers: dict[str, str] = {}
    values: dict[str, Any] = {}
    for column in model.__table__.columns:
        kind = column.type.impl if isinstance(column.type, sa.types.TypeDecorator) else column.type
        if isinstance(kind, sa.String | sa.Text) and not column.foreign_keys and not column.primary_key:
            if column.name in settings.PROTECTED.get(entity, ()) or any(f in column.name.lower() for f in IDENTIFIER_FRAGMENTS):
                values[column.name] = markers[column.name] = _marker()
    async with session_factory() as session:
        row = await _make(session, model, await _tenant(authed), **values)
        await session.commit()
    if subject_consent is not None:
        subject = getattr(row, settings.EXPORT_ENTITIES[entity]["subject_field"])
        granted = await authed.post("/compliance/consents", json={"subject": str(subject), "purpose": subject_consent})
        assert granted.status_code == 201, granted.text
    return row, markers


async def test_export_has_no_direct_identifiers(authed_client: AsyncClient) -> None:  # noqa: F811
    _need(bool(settings.EXPORT_ENTITIES), "the spec exports nothing")
    entity = _export_entity()
    purpose = settings.EXPORT_CONSENT_PURPOSE
    row, markers = await _export_row(authed_client, entity, purpose)
    response = await authed_client.post("/compliance/exports", json={"entity": entity})
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["rows"]) == 1
    text = response.text
    for marker in markers.values():
        assert marker not in text  # no identifier in the clear
    assert str(row.id) not in text  # ids are pseudonymised
    treatments = settings.EXPORT_FIELDS.get(entity, {})
    exported = data["rows"][0]
    assert set(exported) == {"pseudonym", *(f for f, t in treatments.items() if t != "drop")}  # unlisted and dropped fields are gone
    salt = ("export-salt-" + "x" * 24).encode()
    assert exported["pseudonym"] == service.pseudonym(salt, entity, row.id)
    for field, treatment in treatments.items():
        if treatment == "hash" and field in markers:
            assert exported[field] == service.hash_value(salt, entity, field, markers[field])  # HMAC under the salt
            assert exported[field] != hashlib.sha256(markers[field].encode()).hexdigest()  # never a plain hash
            assert exported[field] != hashlib.sha256((entity + "." + field + ":" + markers[field]).encode()).hexdigest()
        if treatment == "generalise":
            assert exported[field] is None or isinstance(exported[field], int | str)
        if treatment == "keep":
            assert field not in markers and field not in settings.PROTECTED.get(entity, ())
    for field in settings.PROTECTED.get(entity, ()):
        assert treatments.get(field, "drop") in ("hash", "drop")
    unauthorised = await authed_client.post("/compliance/exports", json={"entity": "Nope"})
    assert unauthorised.status_code == 422
    monkey_salt = os.environ.pop("COMPLIANCE_EXPORT_SALT")  # no salt, no export
    try:
        assert (await authed_client.post("/compliance/exports", json={"entity": entity})).status_code == 503
    finally:
        os.environ["COMPLIANCE_EXPORT_SALT"] = monkey_salt
    assert await _audit("export.run")
    for detail, _entity, _record in await _audit("export.run"):
        assert set(detail) == {"rows", "skipped_no_consent", "truncated"}


async def test_export_skips_subjects_without_consent(authed_client: AsyncClient) -> None:  # noqa: F811
    _need(bool(settings.EXPORT_ENTITIES) and settings.EXPORT_CONSENT_PURPOSE is not None, "the export is not gated by consent")
    entity = _export_entity()
    purpose = settings.EXPORT_CONSENT_PURPOSE
    assert purpose is not None
    consenting, _ = await _export_row(authed_client, entity, purpose)
    withdrawn, _ = await _export_row(authed_client, entity, purpose)
    silent, _ = await _export_row(authed_client, entity, None)
    subject = str(getattr(withdrawn, settings.EXPORT_ENTITIES[entity]["subject_field"]))
    out = await authed_client.post("/compliance/consents/withdraw", json={"subject": subject, "purpose": purpose})
    assert out.status_code == 200
    response = await authed_client.post("/compliance/exports", json={"entity": entity})
    assert response.status_code == 200, response.text
    data = response.json()
    salt = ("export-salt-" + "x" * 24).encode()
    assert [r["pseudonym"] for r in data["rows"]] == [service.pseudonym(salt, entity, consenting.id)]
    assert data["skipped_no_consent"] == 2
    seen = json.dumps(data)
    assert str(withdrawn.id) not in seen and str(silent.id) not in seen


# --- hardening: races, cascades, vault, tenants, probes ------------------------------------------------------------


async def test_hold_placed_mid_run_protects_the_row(authed_client: AsyncClient) -> None:  # noqa: F811
    _need(bool(settings.RETENTION), "the spec has no retention rule")
    rule = settings.RETENTION[0]
    tenant = await _tenant(authed_client)
    row = await _expired(rule, tenant)
    async with session_factory() as placing:  # a hold being placed: lock taken, row inserted, not committed yet
        await service.lock_entities(placing, [rule["entity"]])
        placing.add(LegalHold(entity=rule["entity"], record_id=row, reason="late hold", placed_by="test", tenant_id=tenant))
        await placing.flush()
        run = asyncio.create_task(_run(authed_client))
        await asyncio.sleep(1.0)
        assert not run.done()  # the run waits for the hold instead of reading a list that is about to be stale
        await placing.commit()
    body = await run
    assert await _state(rule, row) == "kept"
    assert _summary(body, rule)["held"] >= 1


def _cascade_pair() -> tuple[dict[str, Any], str, str] | None:
    for rule in settings.RETENTION:
        if rule["action"] != "purge":
            continue
        table = service.model_for(rule["entity"]).__table__.name
        for dep, fk in service._cascade_edges(table):
            dep_entity = service._entity_of_table(dep)
            if dep_entity is not None:
                return rule, dep_entity, fk
    return None


async def test_purge_does_not_cascade_into_held_children(authed_client: AsyncClient) -> None:  # noqa: F811
    pair = _cascade_pair()
    _need(pair is not None, "no purge rule on an entity whose foreign keys cascade")
    assert pair is not None
    rule, child_entity, fk = pair
    child_model = service.model_for(child_entity)
    tenant = await _tenant(authed_client)
    parent = await _expired(rule, tenant)
    async with session_factory() as session:
        child = (await _make(session, child_model, tenant, **{fk: parent})).id
        await session.commit()

    async def child_exists() -> bool:
        async with session_factory() as session:
            return await session.get(child_model, child) is not None

    held = await authed_client.post("/compliance/legal-holds", json={"entity": child_entity, "record_id": str(child), "reason": "child under hold"})
    assert held.status_code == 201, held.text
    body = await _run(authed_client)
    assert await _state(rule, parent) == "kept" and await child_exists()  # the held child would have gone with it
    assert _summary(body, rule)["held"] >= 1
    assert (await authed_client.delete(f"/compliance/legal-holds/{held.json()['id']}")).status_code == 200

    whole = await authed_client.post("/compliance/legal-holds", json={"entity": child_entity, "reason": "whole child entity"})
    assert whole.status_code == 201, whole.text
    await _run(authed_client)
    assert await _state(rule, parent) == "kept" and await child_exists()
    assert (await authed_client.delete(f"/compliance/legal-holds/{whole.json()['id']}")).status_code == 200

    await _run(authed_client)  # nothing holds anything: the purge goes through, the child with it
    assert await _state(rule, parent) == "gone" and not await child_exists()


def _token_rules() -> list[tuple[dict[str, Any], str, str]]:
    try:
        from app.regulated import settings as rg
    except ImportError:
        return []
    found = []
    for rule in settings.RETENTION:
        table = service.model_for(rule["entity"]).__table__.name
        cols = [
            c for c, r in sorted(rg.PROTECTED.get(table, {}).items())
            if r["mode"] == "tokenise" and (rule["action"] == "purge" or c in rule["anonymise_fields"])
        ]
        if cols:
            found.append((rule, table, cols[0]))
    return found


async def _scalar(sql: str, **params: Any) -> Any:
    async with session_factory() as session:
        return (await session.execute(sa.text(sql), params)).scalar_one_or_none()


async def test_retention_removes_vault_tokens_of_cleared_rows(authed_client: AsyncClient) -> None:  # noqa: F811
    rules = _token_rules()
    _need(bool(rules), "no tokenised field is cleared or purged by a retention rule")
    tenant = await _tenant(authed_client)
    for rule, table, col in rules:
        shared, alone = "shared-" + _token(8), "alone-" + _token(8)
        gone_a = await _expired(rule, tenant, **{col: shared})
        kept_b = await _fresh(rule, tenant, **{col: shared})
        gone_c = await _expired(rule, tenant, **{col: alone})
        token_shared = await _scalar(f"SELECT {col} FROM {table} WHERE id = :i", i=gone_a)  # noqa: S608
        token_alone = await _scalar(f"SELECT {col} FROM {table} WHERE id = :i", i=gone_c)  # noqa: S608
        assert token_shared.startswith("tok_") and shared not in token_shared
        count = "SELECT count(*) FROM regulated_tokens WHERE token = :t"
        assert await _scalar(count, t=token_shared) == 1 and await _scalar(count, t=token_alone) == 1
        await _run(authed_client)
        assert await _state(rule, gone_a) == _done(rule) and await _state(rule, gone_c) == _done(rule)
        assert await _scalar(count, t=token_alone) == 0  # nothing references it any more: the original is not recoverable
        assert await _scalar(count, t=token_shared) == 1  # still used by a live row
        model = service.model_for(rule["entity"])
        async with session_factory() as session:
            await session.execute(
                sa.text(f"UPDATE {table} SET {rule['date_field']} = :t WHERE id = :i"),  # noqa: S608
                {"t": _when(model.__table__.c[rule["date_field"]], rule["days"] + 2), "i": kept_b},
            )
            await session.commit()
        await _run(authed_client)
        assert await _state(rule, kept_b) == _done(rule)
        assert await _scalar(count, t=token_shared) == 0


async def test_tenant_scoping_of_holds_grants_and_audit(authed_client: AsyncClient) -> None:  # noqa: F811
    _need(bool(settings.TENANT_SCOPED) and bool(settings.RETENTION), "not a multi-tenant project with retention")
    rule = settings.RETENTION[0]
    entity = rule["entity"]
    tenant_a = await _tenant(authed_client)
    async with client_for({}) as http:
        b = await sign_in(http, "tenant-b@example.com", roles=list(ALL_ROLES))
        tenant_b = await _tenant(authed_client, "tenant-b@example.com")
        assert tenant_a != tenant_b
        held_a, free_a, row_b = await _expired(rule, tenant_a), await _expired(rule, tenant_a), await _expired(rule, tenant_b)
        # B cannot hold, or even probe, a record of tenant A
        foreign = await http.post("/compliance/legal-holds", json={"entity": entity, "record_id": str(held_a), "reason": "probing"}, headers=b)
        missing = await http.post("/compliance/legal-holds", json={"entity": entity, "record_id": str(uuid.uuid4()), "reason": "probing"}, headers=b)
        assert foreign.status_code == missing.status_code == 404
        hold_a = (await authed_client.post("/compliance/legal-holds", json={"entity": entity, "record_id": str(held_a), "reason": "claim A"})).json()
        assert (await http.get("/compliance/legal-holds", headers=b)).json() == []
        assert (await http.delete(f"/compliance/legal-holds/{hold_a['id']}", headers=b)).status_code == 404
        whole_b = await http.post("/compliance/legal-holds", json={"entity": entity, "reason": "claim B"}, headers=b)
        assert whole_b.status_code == 201
        assert {h["id"] for h in (await authed_client.get("/compliance/legal-holds")).json()} == {hold_a["id"]}

        await _run(authed_client)
        assert await _state(rule, held_a) == "kept"  # A's record hold
        assert await _state(rule, free_a) == _done(rule)  # B's whole-entity hold does not cover tenant A's rows
        assert await _state(rule, row_b) == "kept"  # but it does cover B's own

        a_audit = (await authed_client.get("/compliance/audit", params={"limit": 500})).json()
        b_audit = (await http.get("/compliance/audit", params={"limit": 500}, headers=b)).json()
        assert str(held_a) in {r["record_id"] for r in a_audit} and str(held_a) not in {r["record_id"] for r in b_audit}

        if settings.BREAK_GLASS["enabled"]:
            body = {"reason": "emergency in tenant A", "entities": [entity], "minutes": 5}
            grant = (await authed_client.post("/compliance/break-glass", json=body)).json()
            assert grant["id"] not in {g["id"] for g in (await http.get("/compliance/break-glass", headers=b)).json()}
            assert (await http.post(f"/compliance/break-glass/{grant['id']}/revoke", headers=b)).status_code == 404
            assert (await authed_client.get(f"/compliance/break-glass/{grant['id']}/records/{entity}")).status_code == 200

    nobody = types.SimpleNamespace(id=uuid.uuid4(), roles=[], tenant_id=None)  # an account that belongs to no tenant
    async with session_factory() as session:
        for call in (
            service.place_hold(session, nobody, entity, None, "no tenant"),
            service.list_holds(session, nobody),
            service.list_grants(session, nobody),
            service.list_audit(session, nobody),
            service.break_glass_read(session, nobody, uuid.uuid4(), entity),
            service.export_entity(session, nobody, next(iter(settings.EXPORT_ENTITIES), entity)),
        ):
            with pytest.raises(AppError) as refused:
                await call
            assert refused.value.status_code == 403


async def test_unknown_or_foreign_grant_is_audited(authed_client: AsyncClient) -> None:  # noqa: F811
    _need(bool(BG["enabled"]), "the spec has no break-glass")
    entity = _bg_entity()
    before = len(await _audit("break_glass.denied"))
    assert (await authed_client.get(f"/compliance/break-glass/{uuid.uuid4()}/records/{entity}")).status_code == 403
    async with client_for({}) as http:
        other = await sign_in(http, "grant-owner@example.com", roles=list(ALL_ROLES))
        body = {"reason": "someone else's emergency", "entities": [entity], "minutes": 5}
        theirs = (await http.post("/compliance/break-glass", json=body, headers=other)).json()
    assert (await authed_client.get(f"/compliance/break-glass/{theirs['id']}/records/{entity}")).status_code == 403
    denied = await _audit("break_glass.denied")
    assert len(denied) == before + 2
    assert [d[0]["why"] for d in denied[-2:]] == ["grant", "grant"]
    assert str(theirs["id"]) in json.dumps(denied[-1][0])
