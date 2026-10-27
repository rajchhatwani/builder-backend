"""Org security policies (PLATFORM_SAAS_PLAN §8 "Security policies", §4.4, §12.D.7):
require MFA for all members, and a default session TTL."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.platform import AuditLog, Organization, RefreshToken
from tests.api._mfa_helpers import enroll
from tests.api.conftest import TEST_PASSWORD, ClientFor, TotpClock, bearer_for

Factory = async_sessionmaker[AsyncSession]


async def _acme(owner: AsyncClient) -> str:
    r = await owner.post("/orgs", json={"name": "Acme", "slug": "acme"})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def _join(owner: AsyncClient, member: AsyncClient, role: str = "member") -> None:
    email = member.user.email  # type: ignore[attr-defined]
    inv = await owner.post("/orgs/acme/invitations", json={"email": email, "role": role})
    assert inv.status_code == 201, inv.text
    r = await member.post("/orgs/invitations/accept", json={"token": inv.json()["token"]})
    assert r.status_code == 200, r.text


def _mfa_session(c: AsyncClient, amr: list[str]) -> None:
    c.headers.update(bearer_for(c.user, amr=amr))  # type: ignore[attr-defined]


async def _require_mfa(owner: AsyncClient) -> None:
    _mfa_session(owner, ["pwd", "otp"])
    r = await owner.patch("/orgs/acme/policies", json={"require_mfa": True})
    assert r.status_code == 200, r.text


# -- reading and changing the policies ------------------------------------------------------


async def test_admins_read_the_policies_members_do_not(
    client: AsyncClient, client_for: ClientFor
) -> None:
    await _acme(client)
    bob = await client_for("bob@example.com")
    await _join(client, bob)
    r = await client.get("/orgs/acme/policies")
    assert r.status_code == 200
    assert r.json() == {
        "require_mfa": False,
        "session_ttl_hours": None,
        "members_without_mfa": 2,
        "default_session_hours": 14 * 24,
    }
    r = await bob.get("/orgs/acme/policies")
    assert r.status_code == 403 and r.json()["code"] == "org_role_required"
    org = (await client.get("/orgs/acme")).json()
    assert org["require_mfa"] is False and org["session_ttl_hours"] is None


async def test_turning_on_require_mfa_needs_an_mfa_session_yourself(
    client: AsyncClient, session_factory: Factory
) -> None:
    """So an admin cannot lock themselves out of their own org."""
    await _acme(client)
    r = await client.patch("/orgs/acme/policies", json={"require_mfa": True})
    assert r.status_code == 409 and r.json()["code"] == "enable_mfa_first"
    _mfa_session(client, ["pwd", "otp"])
    r = await client.patch("/orgs/acme/policies", json={"require_mfa": True})
    assert r.status_code == 200 and r.json()["require_mfa"] is True
    async with session_factory() as s:
        row = (
            await s.execute(select(AuditLog).where(AuditLog.action == "org.policy_changed"))
        ).scalar_one()
        assert row.detail == {"require_mfa": True}


async def test_session_ttl_bounds(client: AsyncClient) -> None:
    await _acme(client)
    for bad in (0, 721, -1):
        r = await client.patch("/orgs/acme/policies", json={"session_ttl_hours": bad})
        assert r.status_code == 422
    r = await client.patch("/orgs/acme/policies", json={"session_ttl_hours": 8})
    assert r.status_code == 200 and r.json()["session_ttl_hours"] == 8
    r = await client.patch("/orgs/acme/policies", json={"session_ttl_hours": None})
    assert r.status_code == 200 and r.json()["session_ttl_hours"] is None


async def test_policies_need_a_session_not_an_api_token(client: AsyncClient) -> None:
    await _acme(client)
    pat = (
        await client.post("/account/tokens", json={"name": "t", "scopes": ["read", "write"]})
    ).json()["token"]
    r = await client.patch(
        "/orgs/acme/policies",
        json={"session_ttl_hours": 8},
        headers={"Authorization": f"Bearer {pat}"},
    )
    assert r.status_code == 403 and r.json()["code"] == "session_required"


# -- require MFA: enforcement ---------------------------------------------------------------


async def test_members_without_an_mfa_session_are_stopped_at_the_org(
    client: AsyncClient, client_for: ClientFor
) -> None:
    await _acme(client)
    bob = await client_for("bob@example.com")
    await _join(client, bob)
    await _require_mfa(client)

    r = await bob.get("/orgs/acme/members")
    assert r.status_code == 403
    body = r.json()
    assert body["code"] == "org_mfa_required"
    assert body["details"][0]["organization_slug"] == "acme"
    assert body["details"][0]["mfa_enabled"] is False
    # The org page itself still answers (the UI shows why), and leaving is always possible.
    assert (await bob.get("/orgs/acme")).status_code == 200
    # Their personal org is not affected.
    assert (await bob.get("/orgs")).status_code == 200

    _mfa_session(bob, ["pwd", "otp"])
    assert (await bob.get("/orgs/acme/members")).status_code == 200


async def test_projects_of_the_org_need_mfa_too(client: AsyncClient, client_for: ClientFor) -> None:
    org_id = await _acme(client)
    r = await client.post("/projects", json={"name": "Shop", "organization_id": org_id})
    project_id = r.json()["id"]
    await _require_mfa(client)
    assert (await client.get(f"/projects/{project_id}")).status_code == 200
    _mfa_session(client, ["pwd"])  # same person, password-only session
    r = await client.get(f"/projects/{project_id}")
    assert r.status_code == 403 and r.json()["code"] == "org_mfa_required"


async def test_an_sso_session_satisfies_require_mfa(
    client: AsyncClient, client_for: ClientFor
) -> None:
    """The IdP owns the second factor for SSO sign-ins (agent 5's note; §4.2 + §4.4)."""
    await _acme(client)
    bob = await client_for("bob@example.com")
    await _join(client, bob)
    await _require_mfa(client)
    _mfa_session(bob, ["sso"])
    assert (await bob.get("/orgs/acme/members")).status_code == 200


async def test_api_tokens_follow_their_owner(
    client: AsyncClient, client_for: ClientFor, totp_clock: TotpClock
) -> None:
    await _acme(client)
    bob = await client_for("bob@example.com")
    await _join(client, bob)
    await _require_mfa(client)
    pat = (await bob.post("/account/tokens", json={"name": "t", "scopes": ["read"]})).json()[
        "token"
    ]
    h = {"Authorization": f"Bearer {pat}"}
    r = await bob.get("/orgs/acme/members", headers=h)
    assert r.status_code == 403 and r.json()["code"] == "org_mfa_required"
    await enroll(bob, totp_clock)
    assert (await bob.get("/orgs/acme/members", headers=h)).status_code == 200


async def test_members_cannot_turn_mfa_off_while_an_org_requires_it(
    client: AsyncClient, client_for: ClientFor, totp_clock: TotpClock
) -> None:
    await _acme(client)
    bob = await client_for("bob@example.com")
    await _join(client, bob)
    secret, _ = await enroll(bob, totp_clock)
    await _require_mfa(client)
    status = (await bob.get("/account/mfa")).json()
    assert [o["slug"] for o in status["required_by"]] == ["acme"]
    assert status["session_mfa"] is True
    r = await bob.post(
        "/account/mfa/totp/disable",
        json={"password": TEST_PASSWORD, "code": totp_clock.code(secret)},
    )
    assert r.status_code == 409 and r.json()["code"] == "mfa_required_by_org"
    assert r.json()["details"][0]["organization_slug"] == "acme"


async def test_people_table_shows_2fa(
    client: AsyncClient, client_for: ClientFor, totp_clock: TotpClock
) -> None:
    await _acme(client)
    bob = await client_for("bob@example.com")
    await _join(client, bob)
    await enroll(bob, totp_clock)
    rows = {m["email"]: m for m in (await client.get("/orgs/acme/members")).json()["items"]}
    assert rows["bob@example.com"]["mfa_enabled"] is True
    assert rows["primary@example.com"]["mfa_enabled"] is False
    pol = (await client.get("/orgs/acme/policies")).json()
    assert pol["members_without_mfa"] == 1


# -- session TTL ----------------------------------------------------------------------------


async def test_session_ttl_caps_sign_ins_from_their_start(
    client: AsyncClient, anon_client: AsyncClient, session_factory: Factory
) -> None:
    await _acme(client)
    assert (
        await client.patch("/orgs/acme/policies", json={"session_ttl_hours": 8})
    ).status_code == 200
    r = await anon_client.post(
        "/account/login", json={"email": "primary@example.com", "password": TEST_PASSWORD}
    )
    assert r.status_code == 200
    # The cookie lives no longer than the policy allows.
    cookie = r.headers["set-cookie"].lower()
    max_age = int(cookie.split("max-age=")[1].split(";")[0])
    assert 8 * 3600 - 60 <= max_age <= 8 * 3600
    async with session_factory() as s:
        row = (await s.execute(select(RefreshToken))).scalars().all()[-1]
        assert row.expires_at <= datetime.now(UTC) + timedelta(hours=8)
    # Refreshing keeps working inside the window ...
    h = {"X-Requested-With": "builder"}
    assert (await anon_client.post("/account/refresh", headers=h)).status_code == 200
    # ... and stops once the sign-in is older than the policy, however often it rotated.
    async with session_factory() as s:
        await s.execute(
            update(RefreshToken).values(
                family_started_at=datetime.now(UTC) - timedelta(hours=9),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        await s.commit()
    r = await anon_client.post("/account/refresh", headers=h)
    assert r.status_code == 401 and r.json()["code"] == "invalid_session"


async def test_the_strictest_org_policy_wins(
    client: AsyncClient, anon_client: AsyncClient, client_for: ClientFor, session_factory: Factory
) -> None:
    await _acme(client)
    other = await client_for("other@example.com")
    assert (await other.post("/orgs", json={"name": "Beta", "slug": "beta"})).status_code == 201
    inv = await other.post(
        "/orgs/beta/invitations", json={"email": "primary@example.com", "role": "member"}
    )
    await client.post("/orgs/invitations/accept", json={"token": inv.json()["token"]})
    await client.patch("/orgs/acme/policies", json={"session_ttl_hours": 24})
    await other.patch("/orgs/beta/policies", json={"session_ttl_hours": 2})
    r = await anon_client.post(
        "/account/login", json={"email": "primary@example.com", "password": TEST_PASSWORD}
    )
    max_age = int(r.headers["set-cookie"].lower().split("max-age=")[1].split(";")[0])
    assert max_age <= 2 * 3600
    async with session_factory() as s:
        acme = (
            await s.execute(select(Organization).where(Organization.slug == "acme"))
        ).scalar_one()
        assert acme.session_ttl_hours == 24
