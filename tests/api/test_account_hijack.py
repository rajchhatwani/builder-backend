# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)
"""Review F-005: an address typed in at sign-up is not proof of owning it.

Sign-up never verifies the mailbox, so (a) when an IdP later vouches for the address (SCIM link,
SSO sign-in) whatever the first registrant set up is dropped, and (b) a pending invitation can't
be accepted by id until the mailbox was proved (the e-mailed link does that).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.platform import ApiToken, AuditLog, PlatformUser, RefreshToken
from tests.api.conftest import TEST_PASSWORD, ClientFor
from tests.api.test_scim import enterprise_org, provision, scim_token
from tests.api.test_sso_config import dns  # noqa: F401  (fixture)
from tests.api.test_sso_login import (  # noqa: F401  (fixture)
    _error,
    _saml_post,
    _start,
    acme_saml,
)

Factory = async_sessionmaker[AsyncSession]
ATTACKER_PASSWORD = TEST_PASSWORD + "x"
pytestmark = pytest.mark.usefixtures("dns")


async def _register(anon: AsyncClient, email: str) -> dict[str, str]:
    r = await anon.post(
        "/account/register", json={"email": email, "password": ATTACKER_PASSWORD, "name": "x"}
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _user(factory: Factory, email: str) -> PlatformUser:
    async with factory() as s:
        return (
            await s.execute(select(PlatformUser).where(PlatformUser.email == email))
        ).scalar_one()


async def _logs_in(anon: AsyncClient, email: str) -> bool:
    r = await anon.post("/account/login", json={"email": email, "password": ATTACKER_PASSWORD})
    return r.status_code == 200 and "access_token" in r.text


async def test_scim_link_takes_the_account_back_from_the_first_registrant(
    client_for: ClientFor, anon_client: AsyncClient, session_factory: Factory, dns: dict
) -> None:
    owner = await client_for("ph-owner@example.com")
    await enterprise_org(owner, session_factory, dns, "ph-co", "phco.test")
    h = await scim_token(owner, "ph-co")
    attacker = await _register(anon_client, "victim@phco.test")
    pat = await anon_client.post(
        "/account/tokens", headers=attacker, json={"name": "mine", "scopes": ["read"]}
    )
    assert pat.status_code == 201, pat.text
    assert await _logs_in(anon_client, "victim@phco.test")
    before = await _user(session_factory, "victim@phco.test")
    assert before.email_verified_at is None

    await provision(anon_client, h, "victim@phco.test")

    assert not await _logs_in(anon_client, "victim@phco.test")
    after = await _user(session_factory, "victim@phco.test")
    assert after.email_verified_at is not None
    assert after.token_version > before.token_version
    # the sessions and personal access tokens the first registrant held are dead
    assert (await anon_client.get("/account/me", headers=attacker)).status_code == 401
    async with session_factory() as s:
        live_refresh = (
            (
                await s.execute(
                    select(RefreshToken).where(
                        RefreshToken.user_id == after.id, RefreshToken.revoked_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        live_pats = (
            (
                await s.execute(
                    select(ApiToken).where(
                        ApiToken.user_id == after.id, ApiToken.revoked_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        audit = (
            (await s.execute(select(AuditLog).where(AuditLog.action == "scim.user_created")))
            .scalars()
            .all()
        )
    assert live_refresh == [] and live_pats == []
    assert audit[-1].detail["credentials_reset"] is True


async def test_scim_link_keeps_a_verified_accounts_password(
    client_for: ClientFor, anon_client: AsyncClient, session_factory: Factory, dns: dict
) -> None:
    owner = await client_for("ok-owner@example.com")
    await enterprise_org(owner, session_factory, dns, "ok-co", "okco.test")
    h = await scim_token(owner, "ok-co")
    await client_for("real@okco.test", password=ATTACKER_PASSWORD)  # fixture users are verified
    await provision(anon_client, h, "real@okco.test")
    assert await _logs_in(anon_client, "real@okco.test")


async def test_sso_jit_takes_an_unverified_account_back(
    anon_client: AsyncClient, session_factory: Factory, acme_saml: str
) -> None:
    attacker = await _register(anon_client, "dave@acme.test")
    assert await _logs_in(anon_client, "dave@acme.test")
    request_id, browser, _ = await _start(anon_client)
    assert (
        _error(await _saml_post(anon_client, request_id, browser, email="dave@acme.test")) is None
    )
    assert not await _logs_in(anon_client, "dave@acme.test")
    assert (await anon_client.get("/account/me", headers=attacker)).status_code == 401
    assert (await _user(session_factory, "dave@acme.test")).email_verified_at is not None


async def test_sso_jit_keeps_a_verified_accounts_password(
    anon_client: AsyncClient, client_for: ClientFor, acme_saml: str
) -> None:
    await client_for("dave@acme.test", password=ATTACKER_PASSWORD)
    request_id, browser, _ = await _start(anon_client)
    assert (
        _error(await _saml_post(anon_client, request_id, browser, email="dave@acme.test")) is None
    )
    assert await _logs_in(anon_client, "dave@acme.test")


async def _invite(owner: AsyncClient, email: str) -> str:
    await owner.post("/orgs", json={"name": "Inv", "slug": "inv-co"})
    r = await owner.post("/orgs/inv-co/invitations", json={"email": email, "role": "member"})
    assert r.status_code == 201, r.text
    return r.json()["token"]


async def test_invite_cannot_be_accepted_by_id_before_the_mailbox_is_proved(
    client_for: ClientFor, anon_client: AsyncClient
) -> None:
    owner = await client_for("inv-owner@example.com")
    await _invite(owner, "target@corp.test")
    mallory = await _register(anon_client, "target@corp.test")

    pending = await anon_client.get("/orgs/invitations/pending", headers=mallory)
    assert pending.status_code == 200 and pending.json()["items"] == []
    invitation = (await owner.get("/orgs/inv-co/invitations")).json()["items"][0]
    r = await anon_client.post(f"/orgs/invitations/{invitation['id']}/accept", headers=mallory)
    assert r.status_code == 403 and r.json()["code"] == "email_not_verified"
    members = (await owner.get("/orgs/inv-co/members")).json()["items"]
    assert [m["email"] for m in members] == ["inv-owner@example.com"]


async def test_the_emailed_link_proves_the_mailbox_for_later_invites(
    client_for: ClientFor, anon_client: AsyncClient, session_factory: Factory
) -> None:
    owner = await client_for("inv-owner@example.com")
    token = await _invite(owner, "target@corp.test")
    target = await _register(anon_client, "target@corp.test")
    r = await anon_client.post("/orgs/invitations/accept", headers=target, json={"token": token})
    assert r.status_code == 200, r.text
    assert (await _user(session_factory, "target@corp.test")).email_verified_at is not None

    await owner.post("/orgs", json={"name": "Second", "slug": "second-co"})
    await owner.post(
        "/orgs/second-co/invitations", json={"email": "target@corp.test", "role": "member"}
    )
    pending = (await anon_client.get("/orgs/invitations/pending", headers=target)).json()["items"]
    assert len(pending) == 1
    ok = await anon_client.post(f"/orgs/invitations/{pending[0]['id']}/accept", headers=target)
    assert ok.status_code == 200, ok.text
