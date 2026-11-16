"""SCIM / SSO edge cases: the IdP's bearer is the only credential, so it must not grant more than a
member row, setup routes must refuse API tokens, and hostile directory input must not escalate."""

import asyncio
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.main import app
from app.models.enums import OrgRole
from app.models.platform import OrganizationMember, PlatformUser
from tests.api.conftest import ClientFor
from tests.api.test_scim import (  # noqa: F401 - `dns` is a fixture
    SCIM,
    dns,
    enterprise_org,
    member_role,
    ops,
    provision,
    scim_token,
    user_body,
)

Factory = async_sessionmaker[AsyncSession]
pytestmark = pytest.mark.usefixtures("dns")


async def _status(call: object) -> int:
    """Status of a request; an exception that escapes the app is what the server would turn into a 500."""
    try:
        return int((await call).status_code)  # type: ignore[misc, attr-defined]
    except Exception:  # noqa: BLE001
        return 599


async def _users(factory: Factory, email_like: str) -> int:
    async with factory() as s:
        rows = await s.execute(select(PlatformUser).where(PlatformUser.email.ilike(email_like)))
        return len(list(rows.scalars()))


async def test_user_body_cannot_smuggle_an_org_role(
    client: AsyncClient, anon_client: AsyncClient, session_factory: Factory, dns: dict[str, list[str]]
) -> None:
    org = await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    body = user_body(
        "mallory@acme.test",
        roles=[{"value": "owner"}, {"value": "admin"}],
        userType="owner",
        groups=[{"value": "owner", "display": "owner"}],
        **{"urn:ietf:params:scim:schemas:extension:enterprise:2.0:User": {"role": "owner"}},
    )
    r = await anon_client.post(f"{SCIM}/Users", json=body, headers=h)
    assert r.status_code in (201, 400, 422), r.text
    if r.status_code == 201:
        assert await member_role(session_factory, org, "mallory@acme.test") == OrgRole.member


async def test_patch_cannot_set_role_attributes(
    client: AsyncClient, anon_client: AsyncClient, session_factory: Factory, dns: dict[str, list[str]]
) -> None:
    org = await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    uid = (await provision(anon_client, h))["id"]
    for path in ("roles", "role", "userType", "groups", "organizationRole"):
        r = await anon_client.patch(
            f"{SCIM}/Users/{uid}", headers=h, json=ops({"op": "replace", "path": path, "value": "owner"})
        )
        assert r.status_code < 500, (path, r.status_code)
    assert await member_role(session_factory, org, "alice@acme.test") == OrgRole.member


async def test_case_and_whitespace_variants_do_not_duplicate_an_account(
    client: AsyncClient, anon_client: AsyncClient, session_factory: Factory, dns: dict[str, list[str]]
) -> None:
    await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    await provision(anon_client, h, "alice@acme.test")
    for variant in ("ALICE@acme.test", "Alice@ACME.TEST", " alice@acme.test", "alice@acme.test "):
        r = await anon_client.post(f"{SCIM}/Users", json=user_body(variant), headers=h)
        assert r.status_code in (400, 409), (variant, r.status_code)
    assert await _users(session_factory, "%alice@acme.test%") == 1


async def test_parallel_provisioning_of_one_user_creates_one_account(
    client: AsyncClient, anon_client: AsyncClient, session_factory: Factory, dns: dict[str, list[str]]
) -> None:
    await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    bad: list[str] = []
    for n in range(6):  # several rounds: the race window is narrow
        email = f"dup{n}@acme.test"
        codes = sorted(
            await asyncio.gather(
                *(_status(anon_client.post(f"{SCIM}/Users", json=user_body(email), headers=h)) for _ in range(8))
            )
        )
        if any(c >= 500 for c in codes) or codes.count(201) != 1:
            bad.append(f"{email}: {codes}")
        assert await _users(session_factory, email) == 1
    assert bad == [], "a lost race must answer 409, not an unhandled IntegrityError"


async def test_put_cannot_take_over_another_accounts_email(
    client: AsyncClient,
    client_for: ClientFor,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    uid = (await provision(anon_client, h, "alice@acme.test"))["id"]
    await client_for("bob@acme.test")  # an existing account that is not Alice
    r = await anon_client.put(f"{SCIM}/Users/{uid}", headers=h, json=user_body("bob@acme.test"))
    assert r.status_code in (400, 409), r.text
    r = await anon_client.patch(
        f"{SCIM}/Users/{uid}", headers=h, json=ops({"op": "replace", "path": "userName", "value": "bob@acme.test"})
    )
    assert r.status_code in (400, 409), r.text
    again = (await anon_client.get(f"{SCIM}/Users/{uid}", headers=h)).json()
    assert again["userName"] == "alice@acme.test"


async def test_userName_on_an_unverified_domain_is_refused_on_update_too(
    client: AsyncClient, anon_client: AsyncClient, session_factory: Factory, dns: dict[str, list[str]]
) -> None:
    await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    uid = (await provision(anon_client, h))["id"]
    r = await anon_client.put(f"{SCIM}/Users/{uid}", headers=h, json=user_body("victim@gmail.com"))
    assert r.status_code in (400, 409), r.text
    assert await _users(session_factory, "victim@gmail.com") == 0


async def test_paging_and_filter_boundaries_never_500(
    client: AsyncClient, anon_client: AsyncClient, session_factory: Factory, dns: dict[str, list[str]]
) -> None:
    await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    await provision(anon_client, h)
    bad = []
    for q in (
        "count=1000000000", "count=-1", "count=0", "startIndex=0", "startIndex=-5",
        "startIndex=99999999999999999999", "count=abc",
        'filter=userName eq "x" or 1=1', 'filter=userName eq "\' OR \'1\'=\'1"',
        'filter=userName eq "a" and', "filter=" + "(" * 500, 'filter=userName co "%"',
        'filter=userName eq "' + "a" * 5000 + '"',
    ):
        code = await _status(anon_client.get(f"{SCIM}/Users?{q}", headers=h))
        if code >= 500:
            bad.append((q[:40], code))
            continue
        r = await anon_client.get(f"{SCIM}/Users?{q}", headers=h)
        if r.status_code == 200:
            assert len(r.json().get("Resources", [])) <= 200, q[:40]
            if "or 1=1" in q or "OR" in q:
                # an injected tautology must not widen the result to others' users
                assert r.json()["totalResults"] <= 1, q
    assert bad == []


async def test_oversize_and_hostile_bodies_are_refused_cleanly(
    client: AsyncClient, anon_client: AsyncClient, session_factory: Factory, dns: dict[str, list[str]]
) -> None:
    await enterprise_org(client, session_factory, dns)
    h = {**(await scim_token(client)), "Content-Type": "application/scim+json"}
    codes = {
        "big": await _status(anon_client.post(f"{SCIM}/Users", content=b"{" + b" " * 1_100_000 + b"}", headers=h)),
        "deep": await _status(anon_client.post(f"{SCIM}/Users", content=b"[" * 20000 + b"]" * 20000, headers=h)),
        "nulljson": await _status(anon_client.post(f"{SCIM}/Users", content=b"null", headers=h)),
        "str": await _status(anon_client.post(f"{SCIM}/Users", content=b'"x"', headers=h)),
        "badutf": await _status(anon_client.post(f"{SCIM}/Users", content=b"\xff\xfe{", headers=h)),
        "manyops": await _status(anon_client.patch(
            f"{SCIM}/Users/00000000-0000-4000-8000-000000000009",
            json=ops(*({"op": "add", "path": "active", "value": True} for _ in range(5000))),
            headers=h,
        )),
    }
    assert all(c < 500 for c in codes.values()), codes
    assert codes["big"] == 413, codes


async def test_other_credentials_are_not_scim_tokens(
    client: AsyncClient, anon_client: AsyncClient, session_factory: Factory, dns: dict[str, list[str]]
) -> None:
    await enterprise_org(client, session_factory, dns)
    pat = (await client.post("/account/tokens", json={"name": "t", "scopes": ["write"]})).json()["token"]
    session_jwt = client.headers["Authorization"]
    for label, auth in {"api token": f"Bearer {pat}", "session jwt": session_jwt, "empty": "Bearer "}.items():
        r = await anon_client.get(f"{SCIM}/Users", headers={"Authorization": auth})
        assert r.status_code in (401, 429), (label, r.status_code)


async def test_api_token_cannot_rotate_scim_or_edit_sso_or_policies(
    client: AsyncClient, session_factory: Factory, dns: dict[str, list[str]]
) -> None:
    await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    pat = (await client.post("/account/tokens", json={"name": "t", "scopes": ["write"]})).json()["token"]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver", headers={"Authorization": f"Bearer {pat}"}
    ) as api:
        calls = [
            ("POST", "/orgs/acme/scim/token", None),
            ("PATCH", "/orgs/acme/scim", {"active": False}),
            ("DELETE", "/orgs/acme/scim", None),
            ("PATCH", "/orgs/acme/scim", {"group_roles": {"Everyone": "owner"}}),
            ("PATCH", "/orgs/acme/policies", {"require_mfa": True}),
            ("PUT", "/orgs/acme/sso", {"protocol": "oidc"}),
            ("DELETE", "/orgs/acme/sso", None),
            ("POST", "/orgs/acme/sso/activate", None),
            ("POST", "/orgs/acme/sso/domains", {"domain": "evil.example"}),
        ]
        bad = []
        for m, p, body in calls:
            r = await api.request(m, p, json=body) if body is not None else await api.request(m, p)
            if r.status_code < 400 or r.status_code >= 500:
                bad.append(f"{m} {p} -> {r.status_code}")
    assert bad == []
    # the IdP's old token still works: nothing was rotated or deleted
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as anon:
        assert (await anon.get(f"{SCIM}/Users", headers=h)).status_code == 200


async def test_org_member_cannot_read_scim_setup_or_token(
    client: AsyncClient,
    client_for: ClientFor,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    m = await client_for("member@example.com")
    inv = await client.post("/orgs/acme/invitations", json={"email": m.user.email, "role": "member"})  # type: ignore[attr-defined]
    assert (await m.post("/orgs/invitations/accept", json={"token": inv.json()["token"]})).status_code == 200
    for method, path in (("GET", "/orgs/acme/scim"), ("POST", "/orgs/acme/scim/token"), ("PATCH", "/orgs/acme/scim"), ("DELETE", "/orgs/acme/scim"), ("GET", "/orgs/acme/sso")):
        r = await m.request(method, path, json={} if method in ("POST", "PATCH") else None)
        assert r.status_code == 403, (method, path, r.status_code)
        assert "bb_scim_" not in r.text
    # the token a plain member could not mint is not echoed by the status either
    status = (await client.get("/orgs/acme/scim")).json()
    assert h["Authorization"].split(" ")[1] not in str(status)
