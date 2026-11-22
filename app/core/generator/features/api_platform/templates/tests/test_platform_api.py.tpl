"""API platform (generated): scoped hashed keys, the read-only public API, rate limits and installable apps, on the real
database.

The tests read the project's own settings (app/platform_api/settings.py), so they follow whatever the spec declares and
skip a section the spec does not use. Rows are built straight through the entity models."""

import asyncio
import datetime as dt
import hashlib
import random
import string
import time
import types
import uuid
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from app.auth.models import AuthUser
from app.auth.service import effective_roles
from app.db import session_factory
from app.main import app as fastapi_app
from app.models._base import Base
from app.platform_api import events, service, settings
from tests._auth_support import ALL_ROLES, authed_client, client_for, outbox, sign_in  # noqa: F401

ADMIN_EMAIL = "all-roles@example.com"
KEY_HEADER = "X-API-Key"
SANDBOX = [name for name, cfg in sorted(settings.ENTITIES.items()) if cfg["sandbox"]]
NON_SANDBOX = [name for name, cfg in sorted(settings.ENTITIES.items()) if not cfg["sandbox"]]
FIRST = sorted(settings.ENTITIES)[0]


# --- helpers (not tests) -----------------------------------------------------------------------------------------


def _need(condition: bool, why: str) -> None:
    if not condition:
        pytest.skip(why)


def _model_of_table(table: str) -> Any:
    for mapper in Base.registry.mappers:
        if mapper.local_table.name == table:
            return mapper.class_
    raise LookupError(table)


def _model(entity: str) -> Any:
    return _model_of_table(settings.ENTITIES[entity]["table"])


def _token(length: int = 10) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=length))


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


async def _row(entity: str, tenant: uuid.UUID | None) -> uuid.UUID:
    async with session_factory() as session:
        row = await _make(session, _model(entity), tenant)
        await session.commit()
        return row.id  # type: ignore[no-any-return]


async def _tenant(email: str = ADMIN_EMAIL) -> uuid.UUID | None:
    column = getattr(AuthUser, "tenant_id", None)
    if column is None:
        return None
    async with session_factory() as session:
        return (await session.execute(sa.select(column).where(AuthUser.email == email))).scalar_one()  # type: ignore[no-any-return]


async def _create(admin: AsyncClient, scopes: list[str] | None = None, environment: str = "prod", **extra: Any) -> dict[str, Any]:
    body = {"name": "integration " + _token(4), "scopes": scopes or [FIRST], "environment": environment, **extra}
    response = await admin.post("/platform/keys", json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def _public(key: str) -> AsyncClient:
    return client_for({KEY_HEADER: key})


async def _sql(statement: str, **params: Any) -> list[Any]:
    async with session_factory() as session:
        result = await session.execute(sa.text(statement), params)
        await session.commit()
        return list(result.all()) if result.returns_rows else []


async def _audit(action: str) -> list[Any]:
    return await _sql("SELECT detail, target FROM platform_audit WHERE action = :a ORDER BY at, id", a=action)


def _path(entity: str) -> str:
    return "/public/v1/" + settings.ENTITIES[entity]["plural_path"]


def _server_logs(caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]) -> str:
    """What the application logged (the test client's own request log, which echoes the URL it was given, is not it)."""
    records = "\n".join(r.getMessage() for r in caplog.records if not r.name.startswith("httpx"))
    return records + "\n" + capsys.readouterr().out


def _plain_role() -> str | None:
    for role in ALL_ROLES:
        if not effective_roles([role]) & set(settings.ROLES):
            return role
    return None


async def _fresh_window(limit_text: str) -> None:
    """Do not start a burst of calls right before a fixed window rolls over."""
    _, period = service.parse_limit(limit_text)
    left = period - (time.time() % period)
    if left < 3:
        await asyncio.sleep(left + 0.2)


def _installation(**over: Any) -> Any:
    app_name = next(iter(settings.APPS), "app")
    values: dict[str, Any] = {
        "id": uuid.uuid4(), "kind": "app", "app": app_name, "revoked_at": None, "key_hash": hashlib.sha256(b"k").hexdigest(),
        "expires_at": dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
    }
    values.update(over)
    return types.SimpleNamespace(**values)


# --- keys: storage, roles, creation ------------------------------------------------------------------------------


async def test_catalogue_lists_the_public_entities(authed_client: AsyncClient) -> None:  # noqa: F811
    body = (await authed_client.get("/platform/catalogue")).json()
    assert {e["entity"] for e in body["entities"]} == set(settings.ENTITIES)
    for item in body["entities"]:
        assert item["fields"] == list(settings.ENTITIES[item["entity"]]["fields"])
    assert body["rate_limit"] == settings.RATE_LIMIT and body["key_ttl_days"] == settings.KEY_TTL_DAYS
    async with client_for({}) as anonymous:
        assert (await anonymous.get("/platform/catalogue")).status_code == 401


async def test_creating_keys_needs_a_platform_role(authed_client: AsyncClient) -> None:  # noqa: F811
    role = _plain_role()
    _need(role is not None, "every role may manage keys")
    async with client_for(await sign_in(authed_client, "plain-member@example.com", roles=[role], n=3)) as plain:  # type: ignore[list-item]
        body = {"name": "nope", "scopes": [FIRST], "environment": "prod"}
        assert (await plain.post("/platform/keys", json=body)).status_code == 403
        assert (await plain.get("/platform/keys")).status_code == 403
        assert (await plain.get("/platform/apps")).status_code == 403
        assert (await plain.get("/platform/audit")).status_code == 403
    assert (await authed_client.get("/platform/keys")).json() == []


async def test_a_key_is_shown_once_and_only_its_hash_is_stored(
    authed_client: AsyncClient, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]  # noqa: F811
) -> None:
    created = await _create(authed_client)
    key = created["key"]
    assert key.startswith("bbk_p_") and created["prefix"] == key.split("_")[2] and len(created["prefix"]) == 8
    async with _public(key) as http:
        assert (await http.get("/public/v1/me")).status_code == 200
        assert (await http.get("/public/v1/me", params={"api_key": key})).status_code == 401
    listed = (await authed_client.get("/platform/keys")).json()
    assert [k["id"] for k in listed] == [created["id"]] and "key" not in listed[0] and key not in str(listed)
    stored = (await _sql("SELECT key_hash, prefix FROM api_keys WHERE id = :i", i=uuid.UUID(created["id"])))[0]
    assert stored.key_hash == hashlib.sha256(key.encode()).hexdigest() and stored.prefix == created["prefix"]
    tables = [r[0] for r in await _sql("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")]
    for table in tables:  # the plaintext key is in no row of any table
        hits = await _sql(f'SELECT count(*) FROM "{table}" AS x WHERE x::text LIKE :p', p=f"%{key}%")
        assert hits[0][0] == 0, table
    assert key not in _server_logs(caplog, capsys)


async def test_key_creation_is_validated(authed_client: AsyncClient) -> None:  # noqa: F811
    base = {"name": "k", "scopes": [FIRST], "environment": "prod"}
    for bad in (
        {**base, "name": ""},
        {**base, "name": "x" * 81},
        {**base, "scopes": []},
        {**base, "scopes": ["NotAPublicEntity"]},
        {**base, "environment": "staging"},
        {**base, "ttl_days": 0},
        {**base, "ttl_days": settings.KEY_TTL_DAYS + 1},
    ):
        assert (await authed_client.post("/platform/keys", json=bad)).status_code == 422, bad
    created = await _create(authed_client, ttl_days=1)
    expires = dt.datetime.fromisoformat(created["expires_at"])
    assert dt.timedelta(hours=23) < expires - dt.datetime.now(dt.UTC) <= dt.timedelta(days=1, minutes=1)
    default = await _create(authed_client)
    assert dt.datetime.fromisoformat(default["expires_at"]) - dt.datetime.now(dt.UTC) > dt.timedelta(days=settings.KEY_TTL_DAYS - 1)


# --- the public API: scopes, fields, key handling ----------------------------------------------------------------


async def test_a_key_reads_only_its_scopes(authed_client: AsyncClient) -> None:  # noqa: F811
    _need(len(settings.ENTITIES) > 1, "one public entity only")
    other = sorted(settings.ENTITIES)[1]
    tenant = await _tenant()
    await _row(FIRST, tenant)
    key = (await _create(authed_client, [FIRST]))["key"]
    async with _public(key) as http:
        me = (await http.get("/public/v1/me")).json()
        assert me["scopes"] == [FIRST] and me["environment"] == "prod"
        assert (await http.get(_path(FIRST))).status_code == 200
        denied = await http.get(_path(other))
        assert denied.status_code == 403
        assert (await http.get(f"{_path(other)}/{uuid.uuid4()}")).status_code == 403
    assert any(d.detail["reason"] == "scope" for d in await _audit("public.denied"))


async def test_only_the_listed_fields_are_returned(authed_client: AsyncClient) -> None:  # noqa: F811
    tenant = await _tenant()
    row_id = await _row(FIRST, tenant)
    key = (await _create(authed_client, [FIRST]))["key"]
    allowed = set(settings.ENTITIES[FIRST]["fields"]) | {"id"}
    hidden = {c.name for c in _model(FIRST).__table__.columns} - allowed
    async with _public(key) as http:
        listed = (await http.get(_path(FIRST))).json()
        one = (await http.get(f"{_path(FIRST)}/{row_id}")).json()
        assert listed and one["id"] == str(row_id)
        for item in [*listed, one]:
            assert set(item) == allowed
            assert not hidden & set(item)
        assert (await http.get(f"{_path(FIRST)}/{uuid.uuid4()}")).status_code == 404
        assert (await http.get(_path(FIRST), params={"limit": 0})).status_code == 422
        assert (await http.get(_path(FIRST), params={"limit": 101})).status_code == 422
        assert len((await http.get(_path(FIRST), params={"limit": 1})).json()) == 1


async def test_a_key_in_the_query_string_is_refused(
    authed_client: AsyncClient, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]  # noqa: F811
) -> None:
    key = (await _create(authed_client))["key"]
    async with client_for({}) as anonymous:
        assert (await anonymous.get("/public/v1/me", params={"api_key": key})).status_code == 401
        assert (await anonymous.get("/public/v1/me", params={"x": key})).status_code == 401
        assert (await anonymous.get(_path(FIRST), params={"key": key})).status_code == 401
    async with _public(key) as http:  # the header does not save a request that also leaks the key in its URL
        assert (await http.get("/public/v1/me", params={"api_key": key})).status_code == 401
    assert key not in _server_logs(caplog, capsys)


async def test_missing_or_malformed_keys_are_refused(authed_client: AsyncClient) -> None:  # noqa: F811
    key = (await _create(authed_client))["key"]
    flipped = key[:-1] + ("a" if key[-1] != "a" else "b")
    for bad in ("", "nonsense", "bbk_p_12345678_" + "x" * 32, flipped, key.replace("bbk_p_", "bbk_s_", 1)):
        async with client_for({KEY_HEADER: bad} if bad else {}) as http:
            assert (await http.get("/public/v1/me")).status_code == 401, bad


async def test_a_revoked_key_fails_on_the_next_call(authed_client: AsyncClient) -> None:  # noqa: F811
    created = await _create(authed_client)
    async with _public(created["key"]) as http:
        assert (await http.get("/public/v1/me")).status_code == 200
        revoked = await authed_client.post(f"/platform/keys/{created['id']}/revoke")
        assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
        assert (await http.get("/public/v1/me")).status_code == 401
        assert (await http.get(_path(FIRST))).status_code == 401
    again = await authed_client.post(f"/platform/keys/{created['id']}/revoke")
    assert again.status_code == 200 and again.json()["revoked_at"] == revoked.json()["revoked_at"]
    assert (await authed_client.post(f"/platform/keys/{uuid.uuid4()}/revoke")).status_code == 404
    assert [d.target for d in await _audit("key.revoke")] == [created["id"]]  # one audit row: the repeat changed nothing
    assert any(d.detail["reason"] == "revoked" for d in await _audit("public.denied"))


async def test_an_expired_key_fails(authed_client: AsyncClient) -> None:  # noqa: F811
    created = await _create(authed_client)
    await _sql("UPDATE api_keys SET expires_at = now() - interval '1 minute' WHERE id = :i", i=uuid.UUID(created["id"]))
    async with _public(created["key"]) as http:
        assert (await http.get("/public/v1/me")).status_code == 401
    assert (await authed_client.get("/platform/keys")).json()[0]["status"] == "expired"
    assert any(d.detail["reason"] == "expired" for d in await _audit("public.denied"))


async def test_a_sandbox_key_cannot_read_a_non_sandbox_entity(authed_client: AsyncClient) -> None:  # noqa: F811
    _need(bool(SANDBOX) and bool(NON_SANDBOX), "needs a sandbox and a non-sandbox public entity")
    refused = await authed_client.post(
        "/platform/keys", json={"name": "s", "scopes": [NON_SANDBOX[0]], "environment": "sandbox"}
    )
    assert refused.status_code == 422
    created = await _create(authed_client, [SANDBOX[0]], "sandbox")
    assert created["key"].startswith("bbk_s_")
    await _row(SANDBOX[0], await _tenant())
    async with _public(created["key"]) as http:
        assert (await http.get(_path(SANDBOX[0]))).status_code == 200
        # a sandbox key whose row was tampered with to carry a non-sandbox scope still cannot reach it
        await _sql("UPDATE api_keys SET scopes = :s WHERE id = :i", s=[NON_SANDBOX[0]], i=uuid.UUID(created["id"]))
        assert (await http.get(_path(NON_SANDBOX[0]))).status_code == 403
    prod = await _create(authed_client, [NON_SANDBOX[0]], "prod")
    async with _public(prod["key"]) as http:
        assert (await http.get(_path(NON_SANDBOX[0]))).status_code == 200


# --- rate limit --------------------------------------------------------------------------------------------------


async def test_rate_limit_is_per_key_and_resets_with_the_window(authed_client: AsyncClient) -> None:  # noqa: F811
    environment = "sandbox" if SANDBOX else "prod"
    text = settings.SANDBOX_RATE_LIMIT if SANDBOX else settings.RATE_LIMIT
    limit, _ = service.parse_limit(text)
    _need(limit <= 200, "limit too large to exhaust in a test")
    scope = SANDBOX[0] if SANDBOX else FIRST
    first = await _create(authed_client, [scope], environment)
    second = await _create(authed_client, [scope], environment)
    await _fresh_window(text)
    async with _public(first["key"]) as one, _public(second["key"]) as two:
        for used in range(1, limit + 1):
            ok = await one.get("/public/v1/me")
            assert ok.status_code == 200
            assert ok.headers["X-RateLimit-Limit"] == str(limit)
            assert ok.headers["X-RateLimit-Remaining"] == str(limit - used)
        blocked = await one.get("/public/v1/me")
        assert blocked.status_code == 429 and blocked.json()["code"] == "rate_limited"
        assert int(blocked.headers["Retry-After"]) >= 1
        assert blocked.headers["X-RateLimit-Limit"] == str(limit) and blocked.headers["X-RateLimit-Remaining"] == "0"
        assert (await one.get(_path(scope))).status_code == 429  # every route shares the key's budget
        other = await two.get("/public/v1/me")  # another key has a budget of its own
        assert other.status_code == 200 and other.headers["X-RateLimit-Remaining"] == str(limit - 1)
        await _sql("UPDATE api_key_usage SET window_start = window_start - interval '2 days' WHERE key_id = :i", i=uuid.UUID(first["id"]))
        assert (await one.get("/public/v1/me")).status_code == 200  # a new window
    assert len([d for d in await _audit("public.denied") if d.detail["reason"] == "rate_limited"]) == 1


# --- tenants -----------------------------------------------------------------------------------------------------


async def test_tenants_cannot_read_or_revoke_each_others_keys_and_rows(authed_client: AsyncClient) -> None:  # noqa: F811
    _need(settings.TENANT_SCOPED, "not a multi-tenant project")
    _need(hasattr(_model(FIRST), "tenant_id"), "the public entity is not tenant scoped")
    tenant_a = await _tenant()
    async with client_for(await sign_in(authed_client, "tenant-b@example.com", roles=list(ALL_ROLES), n=1)) as admin_b:
        tenant_b = await _tenant("tenant-b@example.com")
        assert tenant_a != tenant_b
        row_a, row_b = await _row(FIRST, tenant_a), await _row(FIRST, tenant_b)
        key_a = await _create(authed_client, [FIRST])
        key_b = await _create(admin_b, [FIRST])
        async with _public(key_a["key"]) as a, _public(key_b["key"]) as b:
            ids_a = {i["id"] for i in (await a.get(_path(FIRST))).json()}
            ids_b = {i["id"] for i in (await b.get(_path(FIRST))).json()}
            assert str(row_a) in ids_a and str(row_b) not in ids_a
            assert str(row_b) in ids_b and str(row_a) not in ids_b
            assert (await a.get(f"{_path(FIRST)}/{row_b}")).status_code == 404  # same as an id that does not exist
            assert (await a.get(f"{_path(FIRST)}/{uuid.uuid4()}")).json() == (await a.get(f"{_path(FIRST)}/{row_b}")).json()
            assert (await admin_b.post(f"/platform/keys/{key_a['id']}/revoke")).status_code == 404
            assert (await a.get("/public/v1/me")).status_code == 200  # B could not revoke it
        assert [k["id"] for k in (await authed_client.get("/platform/keys")).json()] == [key_a["id"]]
        assert [k["id"] for k in (await admin_b.get("/platform/keys")).json()] == [key_b["id"]]
        assert all(k["id"] != key_a["id"] for k in (await admin_b.get("/platform/audit")).json()) and not any(
            r["target"] == key_a["id"] for r in (await admin_b.get("/platform/audit")).json()
        )


# --- apps --------------------------------------------------------------------------------------------------------


async def test_installing_an_app_grants_a_subset_of_its_scopes(authed_client: AsyncClient) -> None:  # noqa: F811
    _need(bool(settings.APPS), "no apps declared")
    name = sorted(settings.APPS)[0]
    cfg = settings.APPS[name]
    apps = {a["name"]: a for a in (await authed_client.get("/platform/apps")).json()}
    assert set(apps) == set(settings.APPS) and not apps[name]["installed"] and apps[name]["scopes"] == list(cfg["scopes"])
    assert (await authed_client.post("/platform/apps/not-an-app/install", json={})).status_code == 404
    assert (await authed_client.post(f"/platform/apps/{name}/install", json={"scopes": ["NotOffered"]})).status_code == 422
    assert (await authed_client.post(f"/platform/apps/{name}/install", json={"scopes": []})).status_code == 422
    granted = list(cfg["scopes"][:1])
    installed = await authed_client.post(f"/platform/apps/{name}/install", json={"scopes": granted})
    assert installed.status_code == 201, installed.text
    body = installed.json()
    assert body["granted_scopes"] == granted and body["app"] == name and body["token"].startswith("bbk_p_")
    assert len(body["signing_secret"]) == 64
    async with _public(body["token"]) as http:
        me = (await http.get("/public/v1/me")).json()
        assert me["scopes"] == granted
        outside = [e for e in settings.ENTITIES if e not in granted]
        if outside:
            assert (await http.get(_path(outside[0]))).status_code == 403
    assert (await authed_client.post(f"/platform/apps/{name}/install", json={})).status_code == 409
    listed = {a["name"]: a for a in (await authed_client.get("/platform/apps")).json()}[name]
    assert listed["installed"] and listed["installation_id"] == body["installation_id"] and listed["granted_scopes"] == granted
    keys = (await authed_client.get("/platform/keys")).json()
    assert [(k["kind"], k["app"]) for k in keys] == [("app", name)]
    default = sorted(settings.APPS)[-1]
    if default != name:  # no scopes given: everything the app asks for
        every = await authed_client.post(f"/platform/apps/{default}/install", json={})
        assert every.status_code == 201 and every.json()["granted_scopes"] == list(settings.APPS[default]["scopes"])


async def test_uninstalling_revokes_the_token_and_stops_signed_events(authed_client: AsyncClient) -> None:  # noqa: F811
    _need(bool(settings.APPS), "no apps declared")
    name = sorted(settings.APPS)[0]
    body = (await authed_client.post(f"/platform/apps/{name}/install", json={})).json()
    inst_id = uuid.UUID(body["installation_id"])
    async with session_factory() as session:
        inst = await session.get(service.ApiKey, inst_id)
    assert inst is not None and events.deliverable(inst)
    event_types = settings.APPS[name]["events"]
    if event_types:
        assert events.signed_event(inst, event_types[0], {"id": "x"}) is not None
    assert events.signed_event(inst, "not-declared", {"id": "x"}) is None
    async with _public(body["token"]) as http:
        assert (await http.get("/public/v1/me")).status_code == 200
        done = await authed_client.post(f"/platform/apps/{name}/uninstall")
        assert done.status_code == 200 and done.json() == {"installation_id": body["installation_id"], "status": "uninstalled"}
        assert (await http.get("/public/v1/me")).status_code == 401  # the very next call
    async with session_factory() as session:
        inst = await session.get(service.ApiKey, inst_id)
    assert inst is not None and not events.deliverable(inst)
    for event_type in event_types:
        assert events.signed_event(inst, event_type, {"id": "x"}) is None
    assert (await authed_client.post(f"/platform/apps/{name}/uninstall")).status_code == 404
    assert (await authed_client.post("/platform/apps/not-an-app/uninstall")).status_code == 404
    again = await authed_client.post(f"/platform/apps/{name}/install", json={})  # it can be installed afresh
    assert again.status_code == 201 and again.json()["installation_id"] != body["installation_id"]


async def test_the_audit_trail_has_ids_not_secrets(authed_client: AsyncClient) -> None:  # noqa: F811
    created = await _create(authed_client)
    await authed_client.post(f"/platform/keys/{created['id']}/revoke")
    if settings.APPS:
        name = sorted(settings.APPS)[0]
        await authed_client.post(f"/platform/apps/{name}/install", json={})
        await authed_client.post(f"/platform/apps/{name}/uninstall")
    rows = (await authed_client.get("/platform/audit")).json()
    actions = {r["action"] for r in rows}
    assert {"key.create", "key.revoke"} <= actions
    if settings.APPS:
        assert {"app.install", "app.uninstall"} <= actions
    assert "bbk_" not in str(rows) and created["key"] not in str(rows)
    assert len((await authed_client.get("/platform/audit", params={"limit": 1})).json()) == 1
    assert (await authed_client.get("/platform/audit", params={"limit": 0})).status_code == 422


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(events.SIGNING_KEY_ENV, "test-signing-key-" + "x" * 32)


# --- signed events -----------------------------------------------------------------------------------------------


def test_event_signatures_verify_and_reject_tampering() -> None:
    secret = events.signing_secret_for(uuid.uuid4())
    assert len(secret) == 64 and secret != events.signing_secret_for(uuid.uuid4())
    body = '{"id":"1"}'
    now = int(time.time())
    signature = events.sign(secret, now, body)
    assert signature.startswith("sha256=")
    assert events.verify(secret, now, body, signature)
    assert not events.verify(secret, now, body + " ", signature)  # tampered body
    assert not events.verify(secret, now + 1, body, signature)  # tampered timestamp
    assert not events.verify("0" * 64, now, body, signature)  # wrong secret
    assert not events.verify(secret, now, body, "sha256=" + "0" * 64)
    stale = now - 3600
    assert not events.verify(secret, stale, body, events.sign(secret, stale, body))  # replayed
    assert events.verify(secret, stale, body, events.sign(secret, stale, body), tolerance=7200)
    assert not events.verify(secret, "not-a-number", body, signature)


def test_signed_events_need_an_active_installation_and_a_declared_type() -> None:
    _need(any(cfg["events"] for cfg in settings.APPS.values()), "no app declares an event")
    name = next(n for n, cfg in sorted(settings.APPS.items()) if cfg["events"])
    event_type = settings.APPS[name]["events"][0]
    inst = _installation(app=name)
    event = events.signed_event(inst, event_type, {"id": "7"})
    assert event is not None
    secret = events.signing_secret_for(inst.id)
    assert events.verify(secret, event["headers"][events.HEADER_TIMESTAMP], event["body"], event["headers"][events.HEADER_SIGNATURE])
    assert event["headers"][events.HEADER_TYPE] == event_type
    assert events.signed_event(inst, "not-declared", {}) is None
    assert events.signed_event(_installation(app=name, revoked_at=dt.datetime.now(dt.UTC)), event_type, {}) is None
    assert events.signed_event(_installation(app=name, expires_at=dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)), event_type, {}) is None
    assert events.signed_event(_installation(app=name, kind="key"), event_type, {}) is None


def test_rate_limit_text_is_parsed() -> None:
    assert service.parse_limit("60/minute") == (60, 60)
    assert service.parse_limit("5/second") == (5, 1)
    assert service.parse_limit("100/5minutes") == (100, 300)
    assert service.parse_limit("1000/hour") == (1000, 3600)
    with pytest.raises(ValueError):
        service.parse_limit("fast")


# --- the two doors stay apart ------------------------------------------------------------------------------------


async def test_a_user_token_does_not_open_public_routes(authed_client: AsyncClient) -> None:  # noqa: F811
    assert (await authed_client.get("/public/v1/me")).status_code == 401
    for entity in settings.ENTITIES:
        assert (await authed_client.get(_path(entity))).status_code == 401
    token = authed_client.headers["Authorization"].split(" ", 1)[1]
    async with client_for({KEY_HEADER: token}) as http:  # not even in the key header
        assert (await http.get("/public/v1/me")).status_code == 401


async def test_a_key_opens_nothing_outside_the_public_api(authed_client: AsyncClient) -> None:  # noqa: F811
    key = (await _create(authed_client))["key"]
    paths = sorted(
        {
            route.path
            for route in fastapi_app.routes
            if "GET" in getattr(route, "methods", ()) and "{" not in route.path and not route.path.startswith(("/public", "/docs", "/redoc", "/openapi"))
        }
        | {"/platform/keys", "/platform/catalogue", "/platform/apps", "/platform/audit", "/auth/me"}
    )
    async with client_for({}) as nobody:
        open_to_all = {p for p in paths if 200 <= (await nobody.get(p)).status_code < 300}
    for headers in ({KEY_HEADER: key}, {"Authorization": f"Bearer {key}"}):
        async with client_for(headers) as http:
            for path in paths:
                if path in open_to_all:
                    continue
                status = (await http.get(path)).status_code
                assert not 200 <= status < 300, (path, status)
            assert (await http.get("/platform/keys")).status_code == 401
            assert (await http.post("/platform/keys", json={"name": "x", "scopes": [FIRST], "environment": "prod"})).status_code == 401


async def test_signing_needs_a_server_key_and_the_secret_does_not_depend_on_stored_hashes(
    authed_client: AsyncClient, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    inst_id = uuid.uuid4()
    one = events.signing_secret_for(inst_id)
    monkeypatch.setenv(events.SIGNING_KEY_ENV, "another-signing-key-" + "y" * 32)
    assert events.signing_secret_for(inst_id) != one  # keyed by the server secret, not by anything in the database
    monkeypatch.delenv(events.SIGNING_KEY_ENV)
    with pytest.raises(Exception, match="PLATFORM_SIGNING_KEY"):
        events.signing_secret_for(inst_id)
    _need(bool(settings.APPS), "no apps")
    name = next(iter(settings.APPS))
    resp = await authed_client.post(f"/platform/apps/{name}/install", json={})
    assert resp.status_code == 503 and resp.json()["code"] == "signing_key_missing"
    listed = (await authed_client.get("/platform/apps")).json()
    assert not any(a["installed"] for a in listed if a["name"] == name)  # nothing was stored
