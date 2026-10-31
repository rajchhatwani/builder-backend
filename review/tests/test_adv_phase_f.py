"""Adversarial review: Phase F - impersonation (§4.5, §7.1), per-org export (§9), RLS (§3.3).

Different from the permanent tests in tests/api: this walks the routes recorded by dump_routes.py
(review/artifacts/routes.json), forges viewing tokens with the real signing key, sweeps every RLS
table generically, and greps every table of the database for the viewing token and the canaries.
Run: PYTHONPATH=. uv run python review/tests/dump_routes.py   (first, refreshes routes.json)
     uv run python -m pytest review/tests/test_adv_phase_f.py -p no:cacheprovider -q
"""

import json
import pathlib
import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core import platform_security as sec
from app.core import rls
from app.main import app
from app.models.enums import PlatformRole
from tests.api._auth_helpers import make_auth, make_entity
from tests.api.conftest import _FACTORY, ClientFor
from tests.api.test_impersonation import World, world  # noqa: F401
from tests.api.test_rls import ROLE, _probe, rls_on  # noqa: F401

ROWS = json.loads(pathlib.Path("review/artifacts/routes.json").read_text())
SENSITIVE = ("/tokens", "/auth/secrets", "/export", "/billing/", "/generate/", "/generations/")


def fill(path: str, ids: dict[str, str]) -> str:
    return re.sub(r"{(\w+)}", lambda m: ids.get(m.group(1), str(uuid.uuid4())), path)


def viewing_client(token: str) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    )


async def test_phase_f_routes_are_in_the_recorded_route_table() -> None:
    have = {(r["method"], r["path"]): r["guard"] for r in ROWS}
    assert have[("GET", "/orgs/{slug}/export")] == "org_context"
    assert have[("POST", "/admin/organizations/{org_id}/members/{user_id}/impersonate")] == "admin"
    assert have[("GET", "/admin/impersonation/sessions")] == "admin"
    assert have[("POST", "/admin/impersonation/sessions/{session_id}/end")] == "admin"
    for key in (("GET", "/account/impersonation"), ("POST", "/account/impersonation/writes")):
        assert have[key] == "principal"


async def test_a_viewing_token_with_writes_on_survives_a_walk_of_every_route(world: World) -> None:  # noqa: F811
    viewer, body = await world.view_as()
    await viewer.post("/account/impersonation/writes", json={"enabled": True})
    ids = {
        "slug": "acme",
        "project_id": world.project,
        "org_id": world.org_id,
        "user_id": str(world.owner.user.id),
    }  # type: ignore[attr-defined]
    bad = []
    for r in ROWS:
        if r["guard"] in ("admin", "scim", "public"):
            continue
        resp = await viewer.request(r["method"], fill(r["path"], ids), json={})
        sensitive = any(s in r["path"] for s in SENSITIVE)
        if resp.status_code >= 500:
            bad.append((r["method"], r["path"], resp.status_code, "5xx"))
        if sensitive and resp.status_code < 400:
            bad.append((r["method"], r["path"], resp.status_code, "sensitive route answered"))
        if (
            r["path"].startswith("/orgs/")
            and r["method"] != "GET"
            and resp.status_code < 400
            and r["path"] != "/orgs/{slug}/projects/{project_id}/join"
        ):
            bad.append((r["method"], r["path"], resp.status_code, "org write answered"))
        if (
            r["path"].startswith("/account")
            and r["method"] != "GET"
            and resp.status_code < 400
            and "/impersonation" not in r["path"]
        ):
            bad.append((r["method"], r["path"], resp.status_code, "account write answered"))
    assert bad == [], bad
    assert body["access_token"]


async def test_forged_viewing_tokens_are_refused(world: World, session_factory) -> None:  # noqa: ANN001,F811
    _, body = await world.view_as()
    real_sid = str(body["session_id"])
    operator = str(world.ops.user.id)  # type: ignore[attr-defined]
    member = world.member.user  # type: ignore[attr-defined]
    other_admin = await world.ops.get("/admin/me")
    assert other_admin.status_code == 200

    def forge(user, sid, by, audience=sec.AUDIENCE_APP) -> str:  # noqa: ANN001
        return sec.encode_jwt(
            sec.access_claims(
                user_id=str(user.id),
                audience=audience,
                token_version=user.token_version,
                ttl_seconds=600,
                amr=["pwd", "otp"],
                extra={"imp_sid": sid, "imp_by": by},
            )
        )

    cases = {
        "session of the owner, claimed for another member": forge(member, real_sid, operator),
        "right session, wrong operator": forge(world.owner.user, real_sid, str(uuid.uuid4())),  # type: ignore[attr-defined]
        "no such session": forge(world.owner.user, str(uuid.uuid4()), operator),  # type: ignore[attr-defined]
        "garbage session id": forge(world.owner.user, "not-a-uuid", operator),  # type: ignore[attr-defined]
    }
    for name, token in cases.items():
        async with viewing_client(token) as c:
            assert (await c.get("/orgs/acme")).status_code == 401, name
    # the same claims on the admin audience must never open the admin console either
    adm = forge(world.ops.user, real_sid, operator, sec.AUDIENCE_ADMIN)  # type: ignore[attr-defined]
    async with viewing_client(adm) as c:
        assert (await c.get("/admin/impersonation/sessions")).status_code in (401, 403)
    # and a viewing token is no admin token
    started = (await world.view_as())[1]
    async with viewing_client(started["access_token"]) as c:  # type: ignore[arg-type]
        assert (await c.get("/admin/stats")).status_code == 401
        assert (await c.get("/admin/impersonation/sessions")).status_code == 401
    # imp_* claims on an ordinary token do nothing
    plain = sec.encode_jwt(
        sec.access_claims(
            user_id=str(member.id),
            audience=sec.AUDIENCE_APP,
            token_version=member.token_version,
            ttl_seconds=600,
            extra={"imp_by": operator},
        )
    )
    async with viewing_client(plain) as c:
        assert (await c.get("/account/impersonation")).status_code == 404


async def test_the_viewing_token_and_canaries_appear_in_no_table(world: World) -> None:  # noqa: F811
    await make_auth(world.owner, world.project)
    secret = "smtp-PHASEF-CANARY-31"
    await world.owner.put(
        f"/projects/{world.project}/auth/secrets",
        json={"smtp": {"username": "m", "password": secret}},
    )
    viewer, body = await world.view_as()
    await viewer.post("/account/impersonation/writes", json={"enabled": True})
    await make_entity(viewer, world.project, "Seen")
    await viewer.get(f"/projects/{world.project}/spec")
    await viewer.post("/account/impersonation/end")
    needles = {"viewing token": str(body["access_token"]), "smtp": secret}
    leaks = []
    async with _FACTORY[0]() as s:
        tables = [
            t
            for (t,) in (
                await s.execute(text("select tablename from pg_tables where schemaname='public'"))
            ).all()
        ]
        for t in tables:
            blob = "\n".join(
                (await s.execute(text(f'select row_to_json(x)::text from "{t}" x'))).scalars().all()
            )
            for name, val in needles.items():
                if val in blob and not (
                    name == "smtp" and t == "project_auth_secrets"
                ):  # encrypted there
                    leaks.append((t, name))
    assert leaks == [], leaks


async def test_every_rls_table_hides_the_other_org_from_a_scoped_transaction(
    client_for: ClientFor,
    engine,
    rls_on,  # noqa: ANN001,F811
) -> None:
    a = await client_for("a@example.com")
    b = await client_for("b@example.com")
    for c, n in ((a, "A"), (b, "B")):
        pid = (await c.post("/projects", json={"name": n + "-proj"})).json()["id"]
        await make_entity(c, pid, n + "Entity")
        await make_auth(c, pid)
    org_a = next(o["id"] for o in (await a.get("/orgs")).json()["items"])
    child_belongs = f"project_id IN (SELECT id FROM projects WHERE organization_id = '{org_a}')"
    foreign: dict[str, str] = {}
    for t in rls.ALL_TABLES:
        if t == rls.ORGANIZATIONS_TABLE:
            foreign[t] = f"id <> '{org_a}'"
        elif t == rls.AUDIT_TABLE:
            foreign[t] = f"organization_id IS NOT NULL AND organization_id <> '{org_a}'"
        elif t in rls.PROJECT_CHILD_TABLES:
            foreign[t] = f"NOT ({child_belongs})"
        else:
            foreign[t] = f"organization_id <> '{org_a}'"
    async with _probe(engine, org_a) as scoped:
        for t, cond in foreign.items():
            assert (
                await scoped.execute(text(f"SELECT count(*) FROM {t} WHERE {cond}"))
            ).scalar_one() == 0, t
    async with engine.connect() as plain:  # sanity: the other org's rows really do exist
        for t in (
            "organizations",
            "projects",
            "organization_members",
            "subscriptions",
            "entities",
            "project_members",
            "project_auth_configs",
            "platform_audit_log",
        ):
            n = (
                await plain.execute(text(f"SELECT count(*) FROM {t} WHERE {foreign[t]}"))
            ).scalar_one()
            assert n > 0, f"no foreign rows in {t}: the sweep above proved nothing for it"


async def test_export_of_one_org_contains_nothing_of_another(client_for: ClientFor) -> None:
    a = await client_for("a@one.test")
    b = await client_for("b@two.test")
    for c, slug, canary in ((a, "one", "ONE-CANARY"), (b, "two", "TWO-CANARY")):
        org = (await c.post("/orgs", json={"name": slug, "slug": slug})).json()["id"]
        pid = (await c.post("/projects", json={"name": canary, "organization_id": org})).json()[
            "id"
        ]
        await make_entity(c, pid, canary.title().replace("-", ""))
    exported = (await a.get("/orgs/one/export")).text
    assert (
        "ONE-CANARY" in exported and "TWO-CANARY" not in exported and "b@two.test" not in exported
    )
    assert (await a.get("/orgs/two/export")).status_code == 404
    _ = PlatformRole
