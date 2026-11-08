"""Phase D.5–D.6: "test with my own e-mail" (customer admin), the connection check, and the
operator's SSO status column + test button (§12.D.5, §12.D.6, §7)."""

import urllib.parse
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import platform_security as sec
from app.models.enums import PlatformRole
from app.models.platform import AuditLog, OrganizationMember, PlatformUser
from app.models.sso import SsoConnection
from app.services import oidc
from tests.api.conftest import ClientFor
from tests.api.test_sso_config import (
    OIDC_CONFIG,
    business_org,
    dns,  # noqa: F401  (fixture)
    saml_config,
    verified_domain,
)
from tests.api.test_sso_login import _cookie, _saml_post
from tests.sso_fake_idp import attacker_keys, discovery_document, id_token, jwks

Factory = async_sessionmaker[AsyncSession]
APP = "http://localhost:5173"


@pytest.fixture
def idp(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    state: dict[str, object] = {"discovery": 200, "jwks": 200}

    async def resolve(host: str) -> list[str]:
        return ["93.184.216.34"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(state["discovery"], json=discovery_document())  # type: ignore[arg-type]
        if request.url.path == "/jwks":
            return httpx.Response(state["jwks"], json=jwks())  # type: ignore[arg-type]
        if request.url.path == "/token":
            return httpx.Response(200, json={"id_token": state["id_token"]})
        return httpx.Response(404)

    monkeypatch.setattr(oidc, "_resolve", resolve)
    monkeypatch.setattr(oidc, "TRANSPORT", httpx.MockTransport(handler))
    return state


async def _admin_on_acme(client_for: ClientFor, email: str = "alice@acme.test") -> AsyncClient:
    """The tester: an org admin whose e-mail is on the org's domain."""
    return await client_for(email)


async def _saml_org(
    client: AsyncClient,
    factory: Factory,
    dns: dict[str, list[str]],  # noqa: F811
    *,
    activate: bool = False,
) -> str:
    org = await business_org(client, factory)
    await verified_domain(client, dns)
    assert (await client.put("/orgs/acme/sso", json=saml_config())).status_code == 200
    if activate:
        assert (await client.post("/orgs/acme/sso/activate")).status_code == 200
    return org


async def _start_test(admin: AsyncClient, anon: AsyncClient) -> tuple[str, str, str]:
    """→ (request id or state, binding cookie, IdP URL)."""
    r = await admin.post("/orgs/acme/sso/test")
    assert r.status_code == 200, r.text
    login_url = r.json()["login_url"]
    parsed = urllib.parse.urlsplit(login_url)
    assert parsed.path == "/sso/acme/login"
    go = await anon.get(parsed.path + "?" + parsed.query)
    assert go.status_code == 302, go.text
    location = go.headers["location"]
    browser = _cookie(go, "bb_sso")
    assert browser
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(location).query))
    if "SAMLRequest" in q:
        import base64
        import zlib

        from lxml import etree

        xml = zlib.decompress(base64.b64decode(q["SAMLRequest"]), -15)
        return etree.fromstring(xml).get("ID"), browser, location
    return q["state"], browser, location


def _test_result(response: httpx.Response) -> str:
    assert response.status_code == 302, response.text
    location = response.headers["location"]
    assert location.startswith(APP + "/#/org/acme/sso?"), location
    assert "bb_refresh=" not in response.headers.get("set-cookie", "")
    return urllib.parse.parse_qs(location.split("?", 1)[1])["sso_test"][0]


# -- "test with my own e-mail" --------------------------------------------------------------


async def test_saml_test_before_activation_signs_nobody_in(
    client: AsyncClient,
    client_for: ClientFor,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],  # noqa: F811
) -> None:
    """The point of the test: check the IdP round trip *before* turning SSO on for everyone."""
    await _saml_org(client, session_factory, dns)
    request_id, browser, _ = await _start_test(client, anon_client)
    # The IdP answers for the person who started the test.
    r = await _saml_post(anon_client, request_id, browser, email="primary@example.com")
    # primary@example.com is not on acme.test: valid assertion, but the domain would not route.
    assert _test_result(r) == "email_domain_not_verified"

    alice = await _admin_on_acme(client_for)
    inv = await client.post(
        "/orgs/acme/invitations", json={"email": "alice@acme.test", "role": "admin"}
    )
    await alice.post("/orgs/invitations/accept", json={"token": inv.json()["token"]})
    request_id, browser, _ = await _start_test(alice, anon_client)
    r = await _saml_post(anon_client, request_id, browser, email="alice@acme.test")
    assert _test_result(r) == "ok"

    sso = (await client.get("/orgs/acme/sso")).json()
    assert sso["active"] is False
    assert sso["last_test"]["result"] == "ok"
    assert sso["last_test"]["tested_by_email"] == "alice@acme.test"
    async with session_factory() as s:
        actions = [a.action for a in (await s.execute(select(AuditLog))).scalars()]
        assert "sso.test" in actions and "sso.login" not in actions
        assert "sso.jit_provisioned" not in actions


async def test_test_reports_a_different_idp_account(
    client_for: ClientFor,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],  # noqa: F811
) -> None:
    alice = await _admin_on_acme(client_for)
    await _saml_org(alice, session_factory, dns)
    request_id, browser, _ = await _start_test(alice, anon_client)
    r = await _saml_post(anon_client, request_id, browser, email="bob@acme.test")
    assert _test_result(r) == "email_mismatch"
    async with session_factory() as s:
        # Nobody was provisioned by a test.
        bob = (
            await s.execute(select(PlatformUser).where(PlatformUser.email == "bob@acme.test"))
        ).scalar_one_or_none()
        assert bob is None


async def test_a_failed_signature_is_reported_as_the_test_result(
    client_for: ClientFor,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],  # noqa: F811
) -> None:
    alice = await _admin_on_acme(client_for)
    await _saml_org(alice, session_factory, dns)
    request_id, browser, _ = await _start_test(alice, anon_client)
    r = await _saml_post(
        anon_client, request_id, browser, email="alice@acme.test", keys=attacker_keys()
    )
    assert _test_result(r) == "bad_signature"
    assert (await alice.get("/orgs/acme/sso")).json()["last_test"]["result"] == "bad_signature"


async def test_oidc_test(
    client_for: ClientFor,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],  # noqa: F811
    idp: dict[str, object],
) -> None:
    alice = await _admin_on_acme(client_for)
    await business_org(alice, session_factory)
    await verified_domain(alice, dns)
    assert (await alice.put("/orgs/acme/sso", json=OIDC_CONFIG)).status_code == 200
    state, browser, location = await _start_test(alice, anon_client)
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(location).query))
    assert q["login_hint"] == "alice@acme.test"
    idp["id_token"] = id_token(
        client_id="builder-client", nonce=q["nonce"], email="alice@acme.test"
    )
    cb = await anon_client.get(
        "/sso/oidc/acme/callback",
        params={"state": state, "code": "c"},
        headers={"Cookie": f"bb_sso={browser}"},
    )
    assert _test_result(cb) == "ok"


async def test_test_tickets_are_bound_to_the_org_and_expire(
    client_for: ClientFor,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],  # noqa: F811
) -> None:
    alice = await _admin_on_acme(client_for)
    await _saml_org(alice, session_factory, dns)
    ticket = urllib.parse.parse_qs(
        urllib.parse.urlsplit((await alice.post("/orgs/acme/sso/test")).json()["login_url"]).query
    )["test"][0]
    # Another org's login does not accept it.
    other = await anon_client.get("/sso/beta/login", params={"test": ticket})
    assert "sso_error=" in other.headers["location"]
    # A forged or expired ticket is refused.
    claims = sec.decode_jwt(ticket, audience="builder-sso-test")
    claims["exp"] = int((datetime.now(UTC) - timedelta(minutes=5)).timestamp())
    claims["iat"] = claims["exp"] - 60
    stale = sec.encode_jwt(claims)
    r = await anon_client.get("/sso/acme/login", params={"test": stale})
    assert r.headers["location"].endswith("sso_error=invalid_test_ticket")
    r = await anon_client.get("/sso/acme/login", params={"test": "x.y.z"})
    assert r.headers["location"].endswith("sso_error=invalid_test_ticket")


async def test_starting_a_test_needs_admin_session_and_config(
    client: AsyncClient,
    client_for: ClientFor,
    session_factory: Factory,
) -> None:
    await business_org(client, session_factory)
    r = await client.post("/orgs/acme/sso/test")
    assert r.status_code == 409 and r.json()["code"] == "sso_not_configured"
    bob = await client_for("bob@example.com")
    inv = await client.post(
        "/orgs/acme/invitations", json={"email": "bob@example.com", "role": "member"}
    )
    await bob.post("/orgs/invitations/accept", json={"token": inv.json()["token"]})
    assert (await bob.post("/orgs/acme/sso/test")).status_code == 403


async def test_inactive_connection_still_refuses_normal_logins(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],  # noqa: F811
) -> None:
    await _saml_org(client, session_factory, dns)
    r = await anon_client.get("/sso/acme/login")
    assert r.headers["location"].endswith("sso_error=sso_unavailable")


# -- connection check (customer admin and operator) -----------------------------------------


async def test_check_saml_connection(
    client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],  # noqa: F811
) -> None:
    await _saml_org(client, session_factory, dns)
    r = await client.post("/orgs/acme/sso/check")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["protocol"] == "saml" and body["ok"] is True
    names = {c["name"]: c["status"] for c in body["checks"]}
    assert names["plan"] == "ok" and names["verified_domain"] == "ok"
    assert names["certificate"] in ("ok", "warning")
    assert names["active"] == "warning"  # configured but not switched on yet


async def test_check_oidc_connection_reports_discovery_failures(
    client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],  # noqa: F811
    idp: dict[str, object],
) -> None:
    await business_org(client, session_factory)
    await verified_domain(client, dns)
    await client.put("/orgs/acme/sso", json=OIDC_CONFIG)
    ok = (await client.post("/orgs/acme/sso/check")).json()
    assert ok["ok"] is True
    assert {c["name"]: c["status"] for c in ok["checks"]}["jwks"] == "ok"
    idp["discovery"] = 500
    bad = (await client.post("/orgs/acme/sso/check")).json()
    assert bad["ok"] is False
    disc = next(c for c in bad["checks"] if c["name"] == "discovery")
    assert disc["status"] == "error" and disc["detail"] == "discovery_failed"


async def test_check_without_configuration(client: AsyncClient, session_factory: Factory) -> None:
    await business_org(client, session_factory)
    body = (await client.post("/orgs/acme/sso/check")).json()
    assert body["ok"] is False and body["protocol"] is None
    assert {c["name"]: c["status"] for c in body["checks"]}["configuration"] == "error"


async def test_operator_sees_sso_status_and_can_run_the_check(
    client: AsyncClient,
    client_for: ClientFor,
    session_factory: Factory,
    dns: dict[str, list[str]],  # noqa: F811
) -> None:
    org = await _saml_org(client, session_factory, dns, activate=True)
    support = await client_for(
        "help@example.com", PlatformRole.platform_support, audience=sec.AUDIENCE_ADMIN
    )
    rows = (await support.get("/admin/organizations", params={"q": "acme"})).json()["items"]
    row = next(r for r in rows if r["slug"] == "acme")
    assert row["sso_protocol"] == "saml" and row["sso_active"] is True
    assert row["sso_verified_domains"] == 1 and row["sso_last_test_result"] is None
    assert row["require_mfa"] is False
    detail = (await support.get(f"/admin/organizations/{org}")).json()
    assert detail["sso_protocol"] == "saml"
    # SEC L-1: read-only support must not trigger the outbound check.
    denied = await support.post(f"/admin/organizations/{org}/sso/check")
    assert denied.status_code == 403
    admin = await client_for(
        "root@example.com", PlatformRole.platform_admin, audience=sec.AUDIENCE_ADMIN
    )
    r = await admin.post(f"/admin/organizations/{org}/sso/check")
    assert r.status_code == 200 and r.json()["ok"] is True
    async with session_factory() as s:
        audit = (
            await s.execute(select(AuditLog).where(AuditLog.action == "admin.sso_checked"))
        ).scalar_one()
        assert str(audit.organization_id) == org
    # Customers cannot call the operator route.
    assert (await client.post(f"/admin/organizations/{org}/sso/check")).status_code == 401


async def test_operator_member_list_shows_2fa(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory
) -> None:
    org = await business_org(client, session_factory)
    root = await client_for(
        "root@example.com", PlatformRole.platform_admin, audience=sec.AUDIENCE_ADMIN
    )
    rows = (await root.get(f"/admin/organizations/{org}/members")).json()
    assert rows[0]["mfa_enabled"] is False
    async with session_factory() as s:
        member = (await s.execute(select(OrganizationMember))).scalars().first()
        assert member is not None
    async with session_factory() as s:
        assert (await s.execute(select(SsoConnection))).scalars().first() is None
