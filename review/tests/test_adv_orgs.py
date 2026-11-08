"""Adversarial review: tenant isolation + authorization on /orgs/* (REQ-§2.2, §5, §8, §9).

Each test states the expectation from the plan; a failure is a finding.
Run: uv run python -m pytest review/tests/test_adv_orgs.py -p no:cacheprovider -q
"""

import asyncio
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from tests.api.conftest import ClientFor, bearer_for

pytestmark = pytest.mark.asyncio


async def mk_org(owner: AsyncClient, slug: str, name: str = "Org") -> dict:
    r = await owner.post("/orgs", json={"name": name, "slug": slug})
    assert r.status_code == 201, r.text
    return r.json()


async def set_plan(session_factory, org_id: str, plan: str) -> None:  # noqa: ANN001
    async with session_factory() as s:
        await s.execute(
            text("update subscriptions set plan_id=:p, seat_override=null where organization_id=:o"),
            {"p": plan, "o": org_id},
        )
        await s.commit()


async def join(owner: AsyncClient, slug: str, who: AsyncClient, role: str = "member") -> None:
    inv = await owner.post(f"/orgs/{slug}/invitations", json={"email": who.user.email, "role": role})
    assert inv.status_code == 201, inv.text
    ok = await who.post("/orgs/invitations/accept", json={"token": inv.json()["token"]})
    assert ok.status_code == 200, ok.text


# ---------------------------------------------------------------- tenant isolation ----------

ORG_ROUTES = [
    ("GET", "/orgs/{s}"),
    ("PATCH", "/orgs/{s}"),
    ("DELETE", "/orgs/{s}"),
    ("POST", "/orgs/{s}/deletion/cancel"),
    ("GET", "/orgs/{s}/members"),
    ("PATCH", "/orgs/{s}/members/{u}"),
    ("DELETE", "/orgs/{s}/members/{u}"),
    ("POST", "/orgs/{s}/transfer"),
    ("GET", "/orgs/{s}/invitations"),
    ("POST", "/orgs/{s}/invitations"),
    ("DELETE", "/orgs/{s}/invitations/{i}"),
    ("POST", "/orgs/{s}/invitations/{i}/resend"),
    ("GET", "/orgs/{s}/projects"),
    ("POST", "/orgs/{s}/projects/{i}/join"),
    ("POST", "/orgs/{s}/projects/{i}/transfer"),
    ("GET", "/orgs/{s}/plan"),
    ("POST", "/orgs/{s}/billing/checkout"),
    ("POST", "/orgs/{s}/billing/portal"),
    ("GET", "/orgs/{s}/audit"),
    ("GET", "/orgs/{s}/sso"),
    ("PUT", "/orgs/{s}/sso"),
    ("DELETE", "/orgs/{s}/sso"),
    ("POST", "/orgs/{s}/sso/activate"),
    ("POST", "/orgs/{s}/sso/deactivate"),
    ("POST", "/orgs/{s}/sso/domains"),
    ("POST", "/orgs/{s}/sso/domains/acme.com/verify"),
    ("DELETE", "/orgs/{s}/sso/domains/acme.com"),
    ("POST", "/orgs/{s}/sso/test"),
    ("POST", "/orgs/{s}/sso/check"),
    ("GET", "/orgs/{s}/scim"),
    ("POST", "/orgs/{s}/scim/token"),
    ("PATCH", "/orgs/{s}/scim"),
    ("DELETE", "/orgs/{s}/scim"),
    ("GET", "/orgs/{s}/policies"),
    ("PATCH", "/orgs/{s}/policies"),
]


@pytest.mark.parametrize("slug_variant", ["lower", "UPPER", "Mixed"])
async def test_outsider_gets_404_on_every_org_route(client_for: ClientFor, slug_variant: str) -> None:
    """REQ-§9: org B's user must not reach org A at all — and must not be able to tell it exists."""
    alice = await client_for("alice@example.com")
    mallory = await client_for("mallory@example.com")
    org = await mk_org(alice, "victim-co")
    s = {"lower": "victim-co", "UPPER": "VICTIM-CO", "Mixed": "Victim-Co"}[slug_variant]
    me = str(alice.user.id)
    bad = []
    for method, tpl in ORG_ROUTES:
        path = tpl.format(s=s, u=me, i=uuid.uuid4())
        r = await mallory.request(method, path, json={})
        # An existing-but-forbidden org must look identical to a missing org.
        ghost = await mallory.request(method, tpl.format(s="no-such-org-zz", u=me, i=uuid.uuid4()), json={})
        if r.status_code != 404 or ghost.status_code != 404:
            bad.append((method, path, r.status_code, ghost.status_code))
    assert bad == [], bad
    assert org["slug"] == "victim-co"


async def test_unauthenticated_sweep_all_real_routes(anon_client: AsyncClient) -> None:
    """Non-vacuous replacement for tests/api/test_access_matrix.py's sweep (which walks 0 routes
    on FastAPI 0.156 — see finding F-001).  Every non-public route must answer 401."""
    import json
    import pathlib
    import re

    rows = json.loads(pathlib.Path("review/artifacts/routes.json").read_text())
    from tests.api.test_access_matrix import PUBLIC

    offenders = []
    for row in rows:
        if (row["method"], row["path"]) in PUBLIC or row["path"].startswith("/.well-known"):
            continue
        path = re.sub(r"{(\w+)}", lambda m: str(uuid.uuid4()) if m.group(1).endswith("id") else "x-slug", row["path"])
        if row["guard"] == "scim":
            continue  # SCIM answers its own 401 shape; covered in test_adv_scim
        r = await anon_client.request(row["method"], path, json={})
        if r.status_code != 401:
            offenders.append((row["method"], row["path"], r.status_code))
    assert offenders == [], offenders


# ---------------------------------------------------------------- role abuse -----------------


async def test_admin_cannot_make_or_unmake_owners(client_for: ClientFor, session_factory) -> None:  # noqa: ANN001
    """REQ-§2.2/§8: admins cannot create owners, cannot touch the owner."""
    owner = await client_for("owner@example.com")
    admin = await client_for("admin@example.com")
    member = await client_for("member@example.com")
    org = await mk_org(owner, "roles-co")
    await set_plan(session_factory, org["id"], "team")
    await join(owner, "roles-co", admin, "admin")
    await join(owner, "roles-co", member, "member")

    # promote to owner
    r = await admin.patch(f"/orgs/roles-co/members/{member.user.id}", json={"role": "owner"})
    assert r.status_code in (403, 409, 422), r.text
    # self-promote
    r = await admin.patch(f"/orgs/roles-co/members/{admin.user.id}", json={"role": "owner"})
    assert r.status_code in (403, 409, 422), r.text
    # demote owner
    r = await admin.patch(f"/orgs/roles-co/members/{owner.user.id}", json={"role": "member"})
    assert r.status_code in (403, 409), r.text
    # remove owner
    r = await admin.delete(f"/orgs/roles-co/members/{owner.user.id}")
    assert r.status_code in (403, 409), r.text
    # invite as owner
    r = await admin.post("/orgs/roles-co/invitations", json={"email": "x@example.com", "role": "owner"})
    assert r.status_code in (403, 409, 422), r.text
    # member cannot do admin things
    for method, path, body in [
        ("GET", "/orgs/roles-co/invitations", None),
        ("POST", "/orgs/roles-co/invitations", {"email": "y@example.com", "role": "member"}),
        ("PATCH", f"/orgs/roles-co/members/{admin.user.id}", {"role": "member"}),
        ("GET", "/orgs/roles-co/audit", None),
        ("GET", "/orgs/roles-co/policies", None),
        ("GET", "/orgs/roles-co/sso", None),
        ("GET", "/orgs/roles-co/scim", None),
        ("POST", "/orgs/roles-co/billing/portal", None),
        ("PATCH", "/orgs/roles-co", {"name": "pwn"}),
        ("DELETE", "/orgs/roles-co", None),
        ("POST", "/orgs/roles-co/transfer", {"user_id": str(member.user.id)}),
    ]:
        r = await member.request(method, path, json=body)
        assert r.status_code == 403, (method, path, r.status_code, r.text)
    # admin is not allowed owner-only routes
    for method, path, body in [
        ("DELETE", "/orgs/roles-co", None),
        ("POST", "/orgs/roles-co/transfer", {"user_id": str(admin.user.id)}),
        ("POST", "/orgs/roles-co/deletion/cancel", None),
    ]:
        r = await admin.request(method, path, json=body)
        assert r.status_code == 403, (method, path, r.status_code, r.text)


async def test_403_names_an_owner_for_the_member(client_for: ClientFor, session_factory) -> None:  # noqa: ANN001
    """REQ-§8 'Non-admins get a clear ask-your-admin message ... 403 with the owner's email'."""
    owner = await client_for("owner2@example.com")
    member = await client_for("member2@example.com")
    org = await mk_org(owner, "ask-co")
    await set_plan(session_factory, org["id"], "team")
    await join(owner, "ask-co", member)
    r = await member.get("/orgs/ask-co/invitations")
    assert r.status_code == 403
    assert "owner2@example.com" in r.text, r.text


async def test_last_owner_cannot_leave_or_be_demoted(client_for: ClientFor, session_factory) -> None:  # noqa: ANN001
    owner = await client_for("lo@example.com")
    org = await mk_org(owner, "last-owner")
    await set_plan(session_factory, org["id"], "team")
    r = await owner.patch(f"/orgs/last-owner/members/{owner.user.id}", json={"role": "member"})
    assert r.status_code in (403, 409), r.text
    r = await owner.delete(f"/orgs/last-owner/members/{owner.user.id}")
    assert r.status_code in (403, 409), r.text
    # transfer to self / to non-member / to a random uuid
    for target in [str(owner.user.id), str(uuid.uuid4())]:
        r = await owner.post("/orgs/last-owner/transfer", json={"user_id": target})
        assert r.status_code in (400, 403, 404, 409, 422), r.text


async def test_personal_org_cannot_be_deleted_or_left(client_for: ClientFor) -> None:
    u = await client_for("solo@example.com")
    orgs = (await u.get("/orgs")).json()["items"]
    personal = next(o for o in orgs if o["kind"] == "personal")
    r = await u.delete(f"/orgs/{personal['slug']}")
    assert r.status_code in (400, 403, 409), r.text
    r = await u.delete(f"/orgs/{personal['slug']}/members/{u.user.id}")
    assert r.status_code in (400, 403, 409), r.text


async def test_pat_cannot_use_session_only_routes(client_for: ClientFor, session_factory) -> None:  # noqa: ANN001
    """REQ-§4/§8: API tokens must not manage SSO/SCIM/policies (handlers say 'session_required')."""
    owner = await client_for("pat@example.com")
    org = await mk_org(owner, "pat-co")
    await set_plan(session_factory, org["id"], "enterprise")
    tok = await owner.post("/account/tokens", json={"name": "t", "scopes": ["read", "write"]})
    assert tok.status_code in (200, 201), tok.text
    raw = tok.json().get("token") or tok.json().get("secret")
    assert raw
    h = {"Authorization": f"Bearer {raw}"}
    from httpx import ASGITransport

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver", headers=h) as pat:
        probes = [
            ("PUT", "/orgs/pat-co/sso", {"protocol": "oidc"}),
            ("DELETE", "/orgs/pat-co/sso", None),
            ("POST", "/orgs/pat-co/sso/activate", None),
            ("POST", "/orgs/pat-co/sso/domains", {"domain": "pat-corp.com"}),
            ("POST", "/orgs/pat-co/scim/token", None),
            ("PATCH", "/orgs/pat-co/scim", {"active": True}),
            ("DELETE", "/orgs/pat-co/scim", None),
            ("PATCH", "/orgs/pat-co/policies", {"require_mfa": True}),
            ("POST", "/orgs/pat-co/members/x", None),
            ("POST", "/account/tokens", {"name": "child", "scopes": ["write"]}),  # token minting token
            ("PATCH", "/account/password", {"current_password": "x", "new_password": "y" * 14}),
            ("POST", "/account/mfa/totp/setup", {"password": "x"}),
            ("DELETE", "/orgs/pat-co", None),
        ]
        out = []
        for m, p, b in probes:
            r = await pat.request(m, p, json=b)
            out.append((m, p, r.status_code))
        # Anything 2xx is a finding.
        assert [o for o in out if 200 <= o[2] < 300] == [], out


async def test_stale_session_after_token_version_bump(client_for: ClientFor) -> None:
    """REQ-§4.3: bumping token_version must kill existing access tokens immediately."""
    u = await client_for("stale@example.com")
    assert (await u.get("/orgs")).status_code == 200
    from tests.api.conftest import _FACTORY

    async with _FACTORY[0]() as s:
        await s.execute(text("update platform_users set token_version=token_version+1 where id=:i"), {"i": u.user.id})
        await s.commit()
    r = await u.get("/orgs")
    assert r.status_code == 401, r.status_code
    r = await u.get("/projects")
    assert r.status_code == 401, r.status_code


async def test_suspended_user_blocked(client_for: ClientFor) -> None:
    u = await client_for("susp@example.com")
    from tests.api.conftest import _FACTORY

    async with _FACTORY[0]() as s:
        await s.execute(text("update platform_users set status='suspended' where id=:i"), {"i": u.user.id})
        await s.commit()
    assert (await u.get("/orgs")).status_code in (401, 403)


# ---------------------------------------------------------------- quotas -----------------------


async def test_seat_boundary_and_pending_invites_count(client_for: ClientFor, session_factory) -> None:  # noqa: ANN001
    """REQ-§6.2: members + pending >= cap -> 402.  team plan = 5 seats: owner + 4 invites OK, 5th -> 402."""
    owner = await client_for("seat@example.com")
    org = await mk_org(owner, "seat-co")
    await set_plan(session_factory, org["id"], "team")
    codes = []
    for i in range(6):
        r = await owner.post("/orgs/seat-co/invitations", json={"email": f"p{i}@example.com", "role": "member"})
        codes.append(r.status_code)
    assert codes == [201, 201, 201, 201, 402, 402], codes


async def test_concurrent_invites_for_last_seat(client_for: ClientFor, session_factory) -> None:  # noqa: ANN001
    """REQ-§6.2 'SELECT ... FOR UPDATE serializes concurrent attempts so a double-click can't exceed the cap'."""
    owner = await client_for("race@example.com")
    org = await mk_org(owner, "race-co")
    await set_plan(session_factory, org["id"], "team")
    # fill to 1 seat left: owner + 3 pending
    for i in range(3):
        assert (await owner.post("/orgs/race-co/invitations", json={"email": f"f{i}@example.com", "role": "member"})).status_code == 201
    res = await asyncio.gather(
        *[owner.post("/orgs/race-co/invitations", json={"email": f"r{i}@example.com", "role": "member"}) for i in range(8)]
    )
    ok = [r.status_code for r in res].count(201)
    assert ok == 1, [r.status_code for r in res]
    inv = (await owner.get("/orgs/race-co/invitations")).json()["items"]
    assert len(inv) == 4


async def test_concurrent_accepts_for_last_seat(client_for: ClientFor, session_factory) -> None:  # noqa: ANN001
    """Invites issued while a bigger plan was active; plan dropped; only seats remaining may be accepted."""
    owner = await client_for("race2@example.com")
    org = await mk_org(owner, "race2-co")
    await set_plan(session_factory, org["id"], "business")
    people = [await client_for(f"acc{i}@example.com") for i in range(4)]
    toks = []
    for p in people:
        r = await owner.post("/orgs/race2-co/invitations", json={"email": p.user.email, "role": "member"})
        assert r.status_code == 201
        toks.append(r.json()["token"])
    await set_plan(session_factory, org["id"], "free")  # 1 seat; owner already uses it
    res = await asyncio.gather(*[p.post("/orgs/invitations/accept", json={"token": t}) for p, t in zip(people, toks)])
    assert [r.status_code for r in res].count(200) == 0, [(r.status_code, r.text[:80]) for r in res]


async def test_project_cap_boundary_and_race(client_for: ClientFor, session_factory) -> None:  # noqa: ANN001
    owner = await client_for("proj@example.com")
    org = await mk_org(owner, "proj-co")
    await set_plan(session_factory, org["id"], "team")  # 10 projects
    codes = []
    for i in range(12):
        r = await owner.post("/projects", json={"name": f"p{i}", "slug": f"p{i}", "organization_id": org["id"]})
        codes.append(r.status_code)
    assert codes.count(201) == 10, codes
    # race on free (1 project)
    org2 = await mk_org(owner, "proj2-co")
    await set_plan(session_factory, org2["id"], "free")  # 1 project
    res = await asyncio.gather(
        *[owner.post("/projects", json={"name": f"q{i}", "slug": f"q{i}", "organization_id": org2["id"]}) for i in range(6)]
    )
    assert [r.status_code for r in res].count(201) == 1, [r.status_code for r in res]


async def test_api_token_cap_race(client_for: ClientFor, session_factory) -> None:  # noqa: ANN001
    """free plan: 3 API tokens per user per org.  8 concurrent creates."""
    from tests.api.conftest import _FACTORY

    owner = await client_for("tok@example.com")
    # move personal org to free
    orgs = (await owner.get("/orgs")).json()["items"]
    personal = next(o for o in orgs if o["kind"] == "personal")
    await set_plan(session_factory, personal["id"], "free")
    res = await asyncio.gather(
        *[owner.post("/account/tokens", json={"name": f"t{i}", "scopes": ["read"]}) for i in range(8)]
    )
    ok = [r.status_code for r in res].count(201) + [r.status_code for r in res].count(200)
    assert ok <= 3, [r.status_code for r in res]


# ---------------------------------------------------------------- project IDOR via org routes ---


async def test_cross_org_project_join_and_transfer(client_for: ClientFor, session_factory) -> None:  # noqa: ANN001
    alice = await client_for("a1@example.com")
    bob = await client_for("b1@example.com")
    oa = await mk_org(alice, "alice-co")
    ob = await mk_org(bob, "bob-co")
    await set_plan(session_factory, oa["id"], "team")
    await set_plan(session_factory, ob["id"], "team")
    pa = await alice.post("/projects", json={"name": "secret", "slug": "secret", "organization_id": oa["id"]})
    assert pa.status_code == 201, pa.text
    pid = pa.json()["id"]
    # Bob (admin of bob-co) tries to join alice's project via his own org's route, and via hers
    r = await bob.post(f"/orgs/bob-co/projects/{pid}/join", json={"role": "owner"})
    assert r.status_code == 404, (r.status_code, r.text)
    r = await bob.post(f"/orgs/alice-co/projects/{pid}/join", json={"role": "owner"})
    assert r.status_code == 404, (r.status_code, r.text)
    # Bob tries to pull alice's project into his org
    r = await bob.post(f"/orgs/bob-co/projects/{pid}/transfer", json={"to_slug": "bob-co"})
    assert r.status_code == 404, (r.status_code, r.text)
    # Alice tries to push a project into an org she doesn't own
    r = await alice.post(f"/orgs/alice-co/projects/{pid}/transfer", json={"to_slug": "bob-co"})
    assert r.status_code in (403, 404), (r.status_code, r.text)
    # Bob cannot read it at all
    assert (await bob.get(f"/projects/{pid}")).status_code == 404
    # Bob cannot create a project inside alice's org
    r = await bob.post("/projects", json={"name": "x", "slug": "x", "organization_id": oa["id"]})
    assert r.status_code in (403, 404), (r.status_code, r.text)


async def test_org_audit_never_leaks_other_orgs(client_for: ClientFor, session_factory) -> None:  # noqa: ANN001
    alice = await client_for("au1@example.com")
    bob = await client_for("au2@example.com")
    await mk_org(alice, "audit-a")
    await mk_org(bob, "audit-b")
    await alice.patch("/orgs/audit-a", json={"name": "Renamed-A-secret-marker"})
    rows = (await bob.get("/orgs/audit-b/audit")).json()["items"]
    assert "Renamed-A-secret-marker" not in str(rows)
    for r in rows:
        assert "detail" not in r and "ip" not in r  # §7.1 no detail / client IP


async def test_input_edge_cases(client_for: ClientFor) -> None:
    u = await client_for("edge@example.com")
    cases = [
        {"name": "x" * 101},
        {"name": ""},
        {"name": None},
        {"name": "<script>alert(1)</script>", "slug": "xss-co"},
        {"name": "ünï🙂code", "slug": "uni-co"},
        {"name": "ok", "slug": "Bad Slug!"},
        {"name": "ok", "slug": "-lead"},
        {"name": "ok", "slug": "a" * 101},
        {"name": "ok", "slug": "'; drop table organizations;--"},
        {"name": "ok", "slug": "unclaimed-projects"},  # the holding org's slug
        {"name": "ok", "slug": "admin"},
        {"name": "ok", "slug": "invitations"},  # collides with /orgs/invitations/pending
        {"name": "ok", "slug": "me"},
    ]
    out = []
    for body in cases:
        r = await u.post("/orgs", json=body)
        out.append((body.get("slug") or body.get("name"), r.status_code))
        assert r.status_code < 500, (body, r.status_code, r.text[:200])
    # wrong content type / non-json body
    r = await u.post("/orgs", content=b"name=x", headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code in (415, 422), r.status_code
    r = await u.post("/orgs", content=b"{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    print(out)


async def test_read_only_pat_on_org_writes(client_for: ClientFor, session_factory) -> None:  # noqa: ANN001
    """Do PAT scopes apply to /orgs/* at all?  A `read`-scoped token must not mutate orgs."""
    from httpx import ASGITransport

    from app.main import app

    owner = await client_for("ro@example.com")
    org = await mk_org(owner, "ro-co")
    await set_plan(session_factory, org["id"], "team")
    tok = await owner.post("/account/tokens", json={"name": "ro", "scopes": ["read"]})
    raw = tok.json().get("token") or tok.json().get("secret")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver",
                           headers={"Authorization": f"Bearer {raw}"}) as pat:
        probes = [
            ("PATCH", "/orgs/ro-co", {"name": "pwned"}),
            ("POST", "/orgs/ro-co/invitations", {"email": "z@example.com", "role": "member"}),
            ("POST", "/orgs", {"name": "tokenmade", "slug": "tokenmade"}),
            ("POST", "/orgs/ro-co/billing/checkout", {"plan_id": "business"}),
            ("DELETE", "/orgs/ro-co", None),
        ]
        out = [(m, p, (await pat.request(m, p, json=b)).status_code) for m, p, b in probes]
    assert [o for o in out if 200 <= o[2] < 300] == [], out


async def test_member_visible_fields_vs_plan_section_8(client_for: ClientFor, session_factory) -> None:  # noqa: ANN001
    """REQ-§8 'Members: own profile+tokens, filtered projects list, org name and plan status (no billing details)'.
    People table columns role/email/status/2FA/last sign-in are listed under *Admins*.  Print what a member really gets."""
    owner = await client_for("vis-owner@example.com")
    member = await client_for("vis-member@example.com")
    org = await mk_org(owner, "vis-co")
    await set_plan(session_factory, org["id"], "team")
    await join(owner, "vis-co", member)
    m = (await member.get("/orgs/vis-co/members")).json()["items"][0]
    p = (await member.get("/orgs/vis-co/plan")).json()
    print("MEMBER members-row keys:", sorted(m))
    print("MEMBER plan keys:", sorted(p), "usage:", p.get("usage"))
    leaked = [k for k in m if k in ("mfa_enabled", "last_login_at")]
    billing = [k for k in p if any(s in k for s in ("stripe", "customer", "period", "price", "override"))]
    assert not leaked, f"member sees admin-only people columns: {leaked}"
    assert not billing, f"member sees billing details: {billing}"
