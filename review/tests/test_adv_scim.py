"""Adversarial review: SCIM 2.0 (REQ-§4.3, §12.E, agent_8.md behaviours).
Run: uv run python -m pytest review/tests/test_adv_scim.py -p no:cacheprovider -q
"""

import asyncio
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.models.enums import OrgRole
from app.models.platform import OrganizationMember, PlatformUser
from tests.api.conftest import ClientFor, bearer_for
from tests.api.test_scim import (  # noqa: F401  (dns is a fixture)
    SCIM,
    dns,
    enterprise_org,
    member_role,
    ops,
    provision,
    scim_token,
    user_body,
)
from tests.api.test_sso_config import set_plan, verified_domain

pytestmark = pytest.mark.usefixtures("dns")


async def _two_orgs(client_for, session_factory, dns):  # noqa: ANN001
    a = await client_for("owner-a@example.com")
    b = await client_for("owner-b@example.com")
    oa = await enterprise_org(a, session_factory, dns, "org-a", "alpha.test")
    ob = await enterprise_org(b, session_factory, dns, "org-b", "bravo.test")
    return a, b, oa, ob, await scim_token(a, "org-a"), await scim_token(b, "org-b")


async def test_cross_tenant_scim_by_guessed_ids(client_for: ClientFor, anon_client: AsyncClient, session_factory, dns) -> None:  # noqa: ANN001
    a, b, oa, ob, ha, hb = await _two_orgs(client_for, session_factory, dns)
    victim = await provision(anon_client, hb, "victim@bravo.test")
    vid = victim["id"]
    bad = []
    for m, p, body in [
        ("GET", f"/Users/{vid}", None),
        ("PUT", f"/Users/{vid}", user_body("victim@bravo.test")),
        ("PATCH", f"/Users/{vid}", ops({"op": "replace", "value": {"active": False}})),
        ("DELETE", f"/Users/{vid}", None),
    ]:
        r = await anon_client.request(m, SCIM + p, json=body, headers=ha)
        if r.status_code != 404:
            bad.append((m, p, r.status_code))
    # listing and filtering across tenants
    r = await anon_client.get(f"{SCIM}/Users", params={"filter": 'userName eq "victim@bravo.test"'}, headers=ha)
    assert r.json().get("totalResults") == 0, r.text
    r = await anon_client.get(f"{SCIM}/Users", params={"count": 1000}, headers=ha)
    assert "victim@bravo.test" not in r.text
    assert bad == [], bad
    # victim still active in B
    r = await anon_client.get(f"{SCIM}/Users/{vid}", headers=hb)
    assert r.json()["active"] is True


@pytest.mark.parametrize(
    "email",
    [
        "evil@bravo.test",  # another org's verified domain
        "evil@BRAVO.TEST",
        "evil@alpha.test.attacker.com",  # suffix attack
        "evil@sub.alpha.test",  # subdomain of a verified domain (not itself verified)
        "evil@alpha.test.",  # trailing dot
        "evil@аlpha.test",  # Cyrillic 'а' homograph
        "evil@alpha.test@attacker.com",
        "evil%40alpha.test",
        "evil @alpha.test",
        "evil@xn--lpha-5cd.test",
        "alpha.test",  # no @
        "@alpha.test",
        "",
    ],
)
async def test_scim_cannot_provision_off_domain(email: str, client_for: ClientFor, anon_client: AsyncClient, session_factory, dns) -> None:  # noqa: ANN001
    a, b, oa, ob, ha, hb = await _two_orgs(client_for, session_factory, dns)
    r = await anon_client.post(f"{SCIM}/Users", json=user_body(email), headers=ha)
    assert r.status_code in (400, 403, 409, 422), (email, r.status_code, r.text[:200])
    async with __import__("tests.api.conftest", fromlist=["_FACTORY"])._FACTORY[0]() as s:
        n = (await s.execute(text("select count(*) from platform_users where email like '%evil%'"))).scalar()
    assert n == 0, f"account created for {email!r}"


async def test_scim_on_domain_but_mixed_case_and_plus_tag(client_for: ClientFor, anon_client: AsyncClient, session_factory, dns) -> None:  # noqa: ANN001
    a, b, oa, ob, ha, hb = await _two_orgs(client_for, session_factory, dns)
    r = await anon_client.post(f"{SCIM}/Users", json=user_body("MiXeD.Case+tag@ALPHA.test"), headers=ha)
    assert r.status_code == 201, r.text
    r2 = await anon_client.post(f"{SCIM}/Users", json=user_body("mixed.case+tag@alpha.test"), headers=ha)
    assert r2.status_code == 409, r2.text  # duplicate, case-insensitive


async def test_scim_cannot_touch_staff_or_foreign_member(client_for: ClientFor, anon_client: AsyncClient, session_factory, make_user, dns) -> None:  # noqa: ANN001
    from app.models.enums import PlatformRole

    a, b, oa, ob, ha, hb = await _two_orgs(client_for, session_factory, dns)
    await make_user("root@alpha.test", PlatformRole.platform_admin)
    r = await anon_client.post(f"{SCIM}/Users", json=user_body("root@alpha.test"), headers=ha)
    assert r.status_code in (400, 403, 409), r.text
    r = await anon_client.get(f"{SCIM}/Users", params={"filter": 'userName eq "root@alpha.test"'}, headers=ha)
    assert r.json().get("totalResults", 0) == 0


@pytest.mark.parametrize(
    "flt",
    [
        'userName eq',
        'userName eq "unterminated',
        'userName co "a"',
        'userName eq "a" and active eq true',
        'userName eq "a" or userName eq "b"',
        'not (userName eq "a")',
        '(' * 500 + 'userName eq "a"' + ')' * 500,
        'userName eq "' + "A" * 5000 + '"',
        "emails[type eq \"work\"].value eq \"x\"",
        "' OR 1=1 --",
        'userName eq "\\u0000"',
        'userName eq "a%"',
        'id eq "not-a-uuid"',
        "meta.lastModified gt \"2020-01-01T00:00:00Z\"",
    ],
)
async def test_scim_malformed_filters_never_500(flt: str, client_for: ClientFor, anon_client: AsyncClient, session_factory, dns) -> None:  # noqa: ANN001
    a, b, oa, ob, ha, hb = await _two_orgs(client_for, session_factory, dns)
    for coll in ("Users", "Groups"):
        r = await anon_client.get(f"{SCIM}/{coll}", params={"filter": flt}, headers=ha)
        assert r.status_code < 500, (coll, flt[:60], r.status_code, r.text[:200])


@pytest.mark.parametrize("params", [
    {"count": 0}, {"count": -1}, {"count": 10**9}, {"startIndex": 0}, {"startIndex": -5},
    {"startIndex": 10**12}, {"count": "abc"}, {"startIndex": "1; drop"}, {"count": 2.5},
])
async def test_scim_paging_limits(params, client_for: ClientFor, anon_client: AsyncClient, session_factory, dns) -> None:  # noqa: ANN001
    a, b, oa, ob, ha, hb = await _two_orgs(client_for, session_factory, dns)
    for i in range(3):
        await provision(anon_client, ha, f"u{i}@alpha.test")
    r = await anon_client.get(f"{SCIM}/Users", params=params, headers=ha)
    assert r.status_code < 500, (params, r.status_code, r.text[:200])
    if r.status_code == 200:
        assert len(r.json().get("Resources", [])) <= 200  # bounded page size


async def test_scim_huge_and_hostile_bodies(client_for: ClientFor, anon_client: AsyncClient, session_factory, dns) -> None:  # noqa: ANN001
    a, b, oa, ob, ha, hb = await _two_orgs(client_for, session_factory, dns)
    big = user_body("big@alpha.test")
    big["name"] = {"givenName": "G" * 2_000_000, "familyName": "F"}
    r = await anon_client.post(f"{SCIM}/Users", json=big, headers=ha)
    assert r.status_code < 500, r.status_code  # ideally 413/400
    r = await anon_client.post(f"{SCIM}/Users", content=b"{" * 100000, headers={**ha, "Content-Type": "application/scim+json"})
    assert r.status_code < 500
    r = await anon_client.post(f"{SCIM}/Users", content=b"[]", headers={**ha, "Content-Type": "application/json"})
    assert r.status_code < 500
    r = await anon_client.post(f"{SCIM}/Users", content=b"x", headers={**ha, "Content-Type": "text/plain"})
    assert r.status_code < 500
    nested = {"schemas": [], "userName": "n@alpha.test", "emails": [{"value": "n@alpha.test", "primary": True}] * 50000}
    r = await anon_client.post(f"{SCIM}/Users", json=nested, headers=ha)
    assert r.status_code < 500
    for payload in [user_body("<script>@alpha.test"), user_body("a\x00b@alpha.test"), user_body("é" * 300 + "@alpha.test")]:
        r = await anon_client.post(f"{SCIM}/Users", json=payload, headers=ha)
        assert r.status_code < 500, (r.status_code, r.text[:200])


async def test_scim_patch_quirks_never_500(client_for: ClientFor, anon_client: AsyncClient, session_factory, dns) -> None:  # noqa: ANN001
    a, b, oa, ob, ha, hb = await _two_orgs(client_for, session_factory, dns)
    u = await provision(anon_client, ha, "q@alpha.test")
    payloads = [
        ops({"op": "Replace", "path": "active", "value": "False"}),
        ops({"op": "replace", "value": {"active": "false"}}),
        ops({"op": "add", "path": "emails[type eq \"work\"].value", "value": "q2@alpha.test"}),
        ops({"op": "remove", "path": "userName"}),
        ops({"op": "remove", "path": "emails"}),
        ops({"op": "replace", "path": "userName", "value": "q@bravo.test"}),  # rename off-domain
        ops({"op": "replace", "path": "userName", "value": None}),
        ops({"op": "replace", "path": "id", "value": str(uuid.uuid4())}),
        ops({"op": "replace", "path": "meta.created", "value": "x"}),
        {"schemas": [], "Operations": []},
        {"Operations": "nope"},
        {"Operations": [None, 1, "x"]},
        ops({"op": "move", "path": "x", "value": 1}),
        ops({"op": "replace", "path": "roles", "value": [{"value": "owner"}]}),
        ops({"op": "replace", "path": "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User:organization", "value": "x"}),
    ]
    for p in payloads:
        r = await anon_client.patch(f"{SCIM}/Users/{u['id']}", json=p, headers=ha)
        assert r.status_code < 500, (p, r.status_code, r.text[:200])
    # Rename to another org's domain must never succeed
    r = await anon_client.get(f"{SCIM}/Users/{u['id']}", headers=ha)
    assert r.json()["userName"].endswith("@alpha.test"), r.json()["userName"]
    # nothing granted ownership via 'roles'
    assert await member_role(session_factory, oa, "q@alpha.test") in (OrgRole.member, None)


async def test_deactivate_then_reactivate_and_seat_cap(client_for: ClientFor, anon_client: AsyncClient, session_factory, dns) -> None:  # noqa: ANN001
    a, b, oa, ob, ha, hb = await _two_orgs(client_for, session_factory, dns)
    u = await provision(anon_client, ha, "flip@alpha.test")
    assert await member_role(session_factory, oa, "flip@alpha.test") == OrgRole.member
    r = await anon_client.patch(f"{SCIM}/Users/{u['id']}", json=ops({"op": "replace", "value": {"active": False}}), headers=ha)
    assert r.status_code == 200, r.text
    assert await member_role(session_factory, oa, "flip@alpha.test") is None
    # repeated deactivate is idempotent
    r = await anon_client.patch(f"{SCIM}/Users/{u['id']}", json=ops({"op": "replace", "value": {"active": False}}), headers=ha)
    assert r.status_code == 200
    r = await anon_client.patch(f"{SCIM}/Users/{u['id']}", json=ops({"op": "replace", "value": {"active": True}}), headers=ha)
    assert r.status_code == 200, r.text
    assert await member_role(session_factory, oa, "flip@alpha.test") == OrgRole.member
    # concurrency: 6 parallel reactivates must not duplicate rows (PK) nor 500
    await anon_client.patch(f"{SCIM}/Users/{u['id']}", json=ops({"op": "replace", "value": {"active": False}}), headers=ha)
    res = await asyncio.gather(*[
        anon_client.patch(f"{SCIM}/Users/{u['id']}", json=ops({"op": "replace", "value": {"active": True}}), headers=ha)
        for _ in range(6)
    ])
    assert all(r.status_code < 500 for r in res), [r.status_code for r in res]


async def test_scim_concurrent_creates_respect_seat_cap(client_for: ClientFor, anon_client: AsyncClient, session_factory, dns) -> None:  # noqa: ANN001
    """REQ-§6.2 seats enforced at 'SCIM create'. business plan = 25 seats; set a seat_override of 4."""
    a = await client_for("owner-c@example.com")
    org = await enterprise_org(a, session_factory, dns, "org-c", "charlie.test")
    await set_plan(session_factory, org, "business")
    await set_plan(session_factory, org, "enterprise")
    from tests.api.conftest import _FACTORY

    async with _FACTORY[0]() as s:
        await s.execute(text("update subscriptions set seat_override=4 where organization_id=:o"), {"o": org})
        await s.commit()
    h = await scim_token(a, "org-c")
    res = await asyncio.gather(*[
        anon_client.post(f"{SCIM}/Users", json=user_body(f"n{i}@charlie.test"), headers=h) for i in range(10)
    ])
    created = [r.status_code for r in res].count(201)
    async with _FACTORY[0]() as s:
        n = (await s.execute(text("select count(*) from organization_members where organization_id=:o"), {"o": org})).scalar()
    assert n <= 4, f"seat cap 4 exceeded: {n} members ({created} created; {[r.status_code for r in res]})"


async def test_scim_delete_sole_project_owner_hands_over(client_for: ClientFor, anon_client: AsyncClient, session_factory, dns) -> None:  # noqa: ANN001
    a, b, oa, ob, ha, hb = await _two_orgs(client_for, session_factory, dns)
    u = await provision(anon_client, ha, "dev@alpha.test")
    from tests.api.conftest import _FACTORY

    async with _FACTORY[0]() as s:
        uid = (await s.execute(select(PlatformUser.id).where(PlatformUser.email == "dev@alpha.test"))).scalar_one()
    c = await client_for("dev-session@alpha.test")  # separate account; swap the identity to the SCIM user
    c.headers.update(bearer_for(await _load(uid)))
    pr = await c.post("/projects", json={"name": "devproj", "slug": "devproj", "organization_id": oa})
    assert pr.status_code == 201, pr.text
    r = await anon_client.delete(f"{SCIM}/Users/{u['id']}", headers=ha)
    assert r.status_code == 204, r.text
    # project must still exist and have an owner
    async with _FACTORY[0]() as s:
        owners = (await s.execute(text("select count(*) from project_members where project_id=:p and role='owner'"), {"p": pr.json()["id"]})).scalar()
    assert owners >= 1


async def _load(uid):  # noqa: ANN001
    from tests.api.conftest import _FACTORY

    async with _FACTORY[0]() as s:
        return await s.get(PlatformUser, uid)


async def test_scim_token_surface(client_for: ClientFor, anon_client: AsyncClient, session_factory, dns) -> None:  # noqa: ANN001
    a, b, oa, ob, ha, hb = await _two_orgs(client_for, session_factory, dns)
    # a session bearer on SCIM, a SCIM bearer on app routes, junk bearers
    sess = bearer_for(a.user)
    assert (await anon_client.get(f"{SCIM}/Users", headers=sess)).status_code == 401
    assert (await anon_client.get("/orgs", headers=ha)).status_code == 401
    assert (await anon_client.get("/projects", headers=ha)).status_code == 401
    for bad in ["Bearer ", "Bearer bb_scim_", "Bearer bb_scim_" + "A" * 4096, "Basic Zm9vOmJhcg==", "bearer\tbb_scim_x"]:
        r = await anon_client.get(f"{SCIM}/Users", headers={"Authorization": bad})
        assert r.status_code == 401, (bad[:30], r.status_code)
    # error body is SCIM-shaped
    r = await anon_client.get(f"{SCIM}/Users")
    assert r.status_code == 401 and "scim" in r.text.lower()


async def test_scim_failed_bearer_is_rate_limited(client_for: ClientFor, anon_client: AsyncClient, session_factory, dns) -> None:  # noqa: ANN001
    a, b, oa, ob, ha, hb = await _two_orgs(client_for, session_factory, dns)
    codes = []
    for i in range(60):
        r = await anon_client.get(f"{SCIM}/Users", headers={"Authorization": f"Bearer bb_scim_{uuid.uuid4().hex}"})
        codes.append(r.status_code)
    assert 429 in codes, f"no throttling after 60 bad bearers: {set(codes)}"


async def test_operator_rotation_then_fresh_token_switches_scim_on(client_for: ClientFor, anon_client: AsyncClient, session_factory, make_user, dns) -> None:  # noqa: ANN001
    """agent_9: 'after an operator rotation a fresh token switches SCIM back on'."""
    from app.models.enums import PlatformRole
    from tests.api._mfa_helpers import admin_sign_in
    from tests.api.conftest import TotpClock

    a = await client_for("owner-r@example.com")
    org = await enterprise_org(a, session_factory, dns, "org-r", "romeo.test")
    old = await scim_token(a, "org-r")
    await make_user("op@example.com", PlatformRole.platform_admin)
    clock = TotpClock()
    import app.core.totp as totp
    from types import SimpleNamespace

    totp.time = SimpleNamespace(time=clock.time)  # restored by process end; scoped to this test run
    token, _ = await admin_sign_in(anon_client, clock, "op@example.com")
    admin = {"Authorization": f"Bearer {token}"}
    r = await anon_client.post(f"/admin/organizations/{org}/scim/rotate", json={"reason": "review test"}, headers=admin)
    assert r.status_code in (200, 204), r.text
    assert "token" not in r.text.lower() or "bb_scim_" not in r.text  # operator never sees the token
    assert (await anon_client.get(f"{SCIM}/Users", headers=old)).status_code == 401
    st = (await a.get("/orgs/org-r/scim")).json()
    assert st["active"] is False
    new = await scim_token(a, "org-r")
    st = (await a.get("/orgs/org-r/scim")).json()
    assert st["active"] is True, st
    assert (await anon_client.get(f"{SCIM}/Users", headers=new)).status_code == 200


async def test_group_mapping_limits_and_escalation(client_for: ClientFor, anon_client: AsyncClient, session_factory, dns) -> None:  # noqa: ANN001
    a = await client_for("owner-g@example.com")
    org = await enterprise_org(a, session_factory, dns, "org-g", "golf.test")
    admin = await client_for("admin-g@example.com")
    inv = await a.post("/orgs/org-g/invitations", json={"email": "admin-g@example.com", "role": "admin"})
    await admin.post("/orgs/invitations/accept", json={"token": inv.json()["token"]})
    await scim_token(a, "org-g")
    # 150 mappings
    big = {f"group-{i}": "member" for i in range(150)}
    r = await a.patch("/orgs/org-g/scim", json={"group_roles": big})
    assert r.status_code < 500, r.text[:200]
    # admin cannot add an owner mapping
    r = await admin.patch("/orgs/org-g/scim", json={"group_roles": {"Owners": "owner"}})
    assert r.status_code == 403, (r.status_code, r.text[:200])
    # case games / junk roles
    for gr in [{"x": "OWNER"}, {"x": "root"}, {"": "member"}, {"A" * 5000: "member"}, {"x": None}, "str", ["a"]]:
        r = await a.patch("/orgs/org-g/scim", json={"group_roles": gr})
        assert r.status_code < 500, (gr if len(str(gr)) < 80 else "big", r.status_code)
    # an admin using a case variant of owner
    r = await admin.patch("/orgs/org-g/scim", json={"group_roles": {"x": "OWNER"}})
    assert r.status_code != 200, "admin created an owner mapping via case variant"
