"""Phase D.2–D.4: tenant-first discovery, SAML and OIDC sign-in, JIT provisioning (§4.2).

The browser flow: discovery → GET /sso/{slug}/login (302 to the IdP, binding cookie set) → the
IdP posts back (SAML) or redirects back (OIDC) → session cookie set, 302 to the app → the app
calls /account/refresh like after any page load."""

import base64
import urllib.parse
import uuid
import zlib

import httpx
import pytest
from httpx import AsyncClient
from lxml import etree
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.enums import AccountStatus, OrgRole, PlatformRole
from app.models.platform import AuditLog, Organization, OrganizationMember, PlatformUser
from app.services import oidc
from tests.api.conftest import ClientFor
from tests.api.test_sso_config import (
    OIDC_CONFIG,
    business_org,
    dns,  # noqa: F401  (fixture)
    saml_config,
    set_plan,
    verified_domain,
)
from tests.sso_fake_idp import (
    IDP_SSO_URL,
    OIDC_ISSUER,
    attacker_keys,
    b64,
    discovery_document,
    id_token,
    jwks,
    saml_response_xml,
    sign_assertion,
)

Factory = async_sessionmaker[AsyncSession]
APP = "http://localhost:5173"
CSRF = {"X-Requested-With": "builder"}


@pytest.fixture
async def acme_saml(
    client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],  # noqa: F811
) -> str:
    org = await business_org(client, session_factory)
    await verified_domain(client, dns)
    assert (await client.put("/orgs/acme/sso", json=saml_config())).status_code == 200
    assert (await client.post("/orgs/acme/sso/activate")).status_code == 200
    return org


def _cookie(response: httpx.Response, name: str) -> str | None:
    for header in response.headers.get_list("set-cookie"):
        if header.startswith(name + "="):
            return header.split(";", 1)[0].split("=", 1)[1]
    return None


async def _start(anon: AsyncClient, slug: str = "acme") -> tuple[str, str, str]:
    """→ (request id, binding cookie, IdP redirect URL)."""
    r = await anon.get(f"/sso/{slug}/login")
    assert r.status_code == 302, r.text
    location = r.headers["location"]
    browser = _cookie(r, "bb_sso")
    assert browser
    sso_cookie = next(h for h in r.headers.get_list("set-cookie") if h.startswith("bb_sso="))
    lowered = sso_cookie.lower()
    assert "httponly" in lowered and "secure" in lowered and "samesite=none" in lowered
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(location).query))
    if "SAMLRequest" in query:
        xml = zlib.decompress(base64.b64decode(query["SAMLRequest"]), -15)
        return etree.fromstring(xml).get("ID"), browser, location
    return query["state"], browser, location


async def _saml_post(
    anon: AsyncClient,
    request_id: str,
    browser: str | None,
    *,
    email: str = "alice@acme.test",
    keys: object = None,
    slug: str = "acme",
) -> httpx.Response:
    base = "http://localhost:8000"
    xml = saml_response_xml(
        email=email,
        sp_entity_id=f"{base}/sso/metadata/{slug}",
        acs_url=f"{base}/sso/saml/{slug}/acs",
        in_response_to=request_id,
    )
    signed = sign_assertion(xml, keys) if keys else sign_assertion(xml)  # type: ignore[arg-type]
    headers = {"Cookie": f"bb_sso={browser}"} if browser else {}
    return await anon.post(
        f"/sso/saml/{slug}/acs",
        content=urllib.parse.urlencode({"SAMLResponse": b64(signed), "RelayState": ""}),
        headers={"Content-Type": "application/x-www-form-urlencoded", **headers},
    )


def _error(response: httpx.Response) -> str | None:
    assert response.status_code == 302, response.text
    location = response.headers["location"]
    assert location.startswith(APP + "/#/")
    if "sso_error=" not in location:
        return None
    return location.split("sso_error=", 1)[1]


async def _member(factory: Factory, org: str, email: str) -> OrganizationMember | None:
    async with factory() as session:
        user = (
            await session.execute(select(PlatformUser).where(PlatformUser.email == email))
        ).scalar_one_or_none()
        if user is None:
            return None
        return await session.get(OrganizationMember, (uuid.UUID(org), user.id))


async def _actions(factory: Factory) -> list[str]:
    async with factory() as session:
        return [a.action for a in (await session.execute(select(AuditLog))).scalars()]


# -- discovery ------------------------------------------------------------------------------


async def test_discovery(anon_client: AsyncClient, client: AsyncClient, acme_saml: str) -> None:
    r = await anon_client.post("/account/login/discover", json={"email": "Bob@ACME.test"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["method"] == "sso"
    assert body["login_url"] == "http://localhost:8000/sso/acme/login?login_hint=bob%40acme.test"
    assert body["organization_name"] == "Acme"
    other = await anon_client.post("/account/login/discover", json={"email": "x@elsewhere.test"})
    assert other.json() == {"method": "password", "login_url": None, "organization_name": None}


async def test_discovery_falls_back_when_inactive_or_downgraded(
    anon_client: AsyncClient, client: AsyncClient, session_factory: Factory, acme_saml: str
) -> None:
    await set_plan(session_factory, acme_saml, "team")
    r = await anon_client.post("/account/login/discover", json={"email": "bob@acme.test"})
    assert r.json()["method"] == "password"
    await set_plan(session_factory, acme_saml, "business")
    await client.post("/orgs/acme/sso/deactivate")
    r = await anon_client.post("/account/login/discover", json={"email": "bob@acme.test"})
    assert r.json()["method"] == "password"


# -- SAML -----------------------------------------------------------------------------------


async def test_saml_login_jit_provisions_and_signs_in(
    anon_client: AsyncClient, session_factory: Factory, acme_saml: str
) -> None:
    request_id, browser, location = await _start(anon_client)
    assert location.startswith(IDP_SSO_URL + "?SAMLRequest=")
    r = await _saml_post(anon_client, request_id, browser)
    assert _error(r) is None
    assert r.headers["location"] == APP + "/#/sso/complete"
    assert _cookie(r, "bb_refresh")
    # The app picks the session up like after a reload.
    session = await anon_client.post("/account/refresh", headers=CSRF)
    assert session.status_code == 200, session.text
    assert session.json()["user"]["email"] == "alice@acme.test"
    assert session.json()["user"]["name"] == "Alice Smith"

    member = await _member(session_factory, acme_saml, "alice@acme.test")
    assert member is not None and member.role is OrgRole.member
    async with session_factory() as s:
        user = (
            await s.execute(select(PlatformUser).where(PlatformUser.email == "alice@acme.test"))
        ).scalar_one()
        assert user.default_organization_id == uuid.UUID(acme_saml)
        kinds = (
            (
                await s.execute(
                    select(Organization.kind)
                    .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
                    .where(OrganizationMember.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert sorted(k.value for k in kinds) == ["personal", "team"]
    actions = await _actions(session_factory)
    assert "sso.jit_provisioned" in actions and "sso.login" in actions

    # No password: the password form can never open this account.
    r = await anon_client.post(
        "/account/login", json={"email": "alice@acme.test", "password": "anything-at-all-123"}
    )
    assert r.status_code == 401


async def test_saml_assertion_cannot_be_replayed(
    anon_client: AsyncClient, session_factory: Factory, acme_saml: str
) -> None:
    request_id, browser, _ = await _start(anon_client)
    assert _error(await _saml_post(anon_client, request_id, browser)) is None
    assert _error(await _saml_post(anon_client, request_id, browser)) == "invalid_request_state"


async def test_saml_needs_the_browser_that_started_the_login(
    anon_client: AsyncClient, acme_saml: str
) -> None:
    """Login CSRF: an attacker's own valid response, posted from the victim's browser."""
    request_id, _browser, _ = await _start(anon_client)
    assert _error(await _saml_post(anon_client, request_id, None)) == "invalid_request_state"
    assert _error(await _saml_post(anon_client, request_id, "forged")) == "invalid_request_state"


async def test_saml_unknown_request_id_is_refused(anon_client: AsyncClient, acme_saml: str) -> None:
    _request_id, browser, _ = await _start(anon_client)
    assert _error(await _saml_post(anon_client, "_unsolicited1234", browser)) == (
        "invalid_request_state"
    )


async def test_saml_bad_signature_is_refused_and_audited(
    anon_client: AsyncClient, session_factory: Factory, acme_saml: str
) -> None:
    request_id, browser, _ = await _start(anon_client)
    r = await _saml_post(anon_client, request_id, browser, keys=attacker_keys())
    assert _error(r) == "bad_signature"
    assert await _member(session_factory, acme_saml, "alice@acme.test") is None
    async with session_factory() as s:
        failed = (
            await s.execute(select(AuditLog).where(AuditLog.action == "sso.login_failed"))
        ).scalar_one()
        assert failed.detail == {"reason": "bad_signature", "protocol": "saml"}
        assert failed.organization_id == uuid.UUID(acme_saml)


async def test_email_outside_verified_domains_is_refused(
    anon_client: AsyncClient, client_for: ClientFor, session_factory: Factory, acme_saml: str
) -> None:
    """The org's IdP must never sign in someone else's account (e.g. a gmail.com user)."""
    await client_for("victim@other.test")
    request_id, browser, _ = await _start(anon_client)
    r = await _saml_post(anon_client, request_id, browser, email="victim@other.test")
    assert _error(r) == "email_domain_not_verified"
    assert await _member(session_factory, acme_saml, "victim@other.test") is None


async def test_existing_member_keeps_their_role(
    anon_client: AsyncClient,
    client: AsyncClient,
    client_for: ClientFor,
    session_factory: Factory,
    acme_saml: str,
) -> None:
    await client_for("carol@acme.test")
    async with session_factory() as s:
        carol = (
            await s.execute(select(PlatformUser).where(PlatformUser.email == "carol@acme.test"))
        ).scalar_one()
        s.add(
            OrganizationMember(
                organization_id=uuid.UUID(acme_saml), user_id=carol.id, role=OrgRole.admin
            )
        )
        await s.commit()
    request_id, browser, _ = await _start(anon_client)
    assert (
        _error(await _saml_post(anon_client, request_id, browser, email="carol@acme.test")) is None
    )
    member = await _member(session_factory, acme_saml, "carol@acme.test")
    assert member is not None and member.role is OrgRole.admin
    assert "sso.jit_provisioned" not in await _actions(session_factory)


async def test_existing_account_outside_the_org_is_added_by_jit(
    anon_client: AsyncClient, client_for: ClientFor, session_factory: Factory, acme_saml: str
) -> None:
    await client_for("dave@acme.test")  # signed up with a password before SSO existed
    request_id, browser, _ = await _start(anon_client)
    assert (
        _error(await _saml_post(anon_client, request_id, browser, email="dave@acme.test")) is None
    )
    member = await _member(session_factory, acme_saml, "dave@acme.test")
    assert member is not None and member.role is OrgRole.member


async def test_jit_role_setting(
    anon_client: AsyncClient, client: AsyncClient, session_factory: Factory, acme_saml: str
) -> None:
    await client.put("/orgs/acme/sso", json={**saml_config(), "jit_role": "admin"})
    request_id, browser, _ = await _start(anon_client)
    assert _error(await _saml_post(anon_client, request_id, browser)) is None
    member = await _member(session_factory, acme_saml, "alice@acme.test")
    assert member is not None and member.role is OrgRole.admin


async def test_jit_disabled_admits_only_existing_members(
    anon_client: AsyncClient, client: AsyncClient, session_factory: Factory, acme_saml: str
) -> None:
    await client.put("/orgs/acme/sso", json={**saml_config(), "jit_enabled": False})
    request_id, browser, _ = await _start(anon_client)
    assert _error(await _saml_post(anon_client, request_id, browser)) == "not_provisioned"
    async with session_factory() as s:
        assert (
            await s.execute(select(PlatformUser).where(PlatformUser.email == "alice@acme.test"))
        ).scalar_one_or_none() is None


async def test_jit_respects_the_seat_cap(
    anon_client: AsyncClient, session_factory: Factory, acme_saml: str
) -> None:
    from app.models.platform import Subscription

    async with session_factory() as s:
        sub = await s.get(Subscription, uuid.UUID(acme_saml))
        assert sub is not None
        sub.seat_override = 1  # the owner already fills it
        await s.commit()
    request_id, browser, _ = await _start(anon_client)
    assert _error(await _saml_post(anon_client, request_id, browser)) == "seat_limit"
    actions = await _actions(session_factory)
    assert "quota.denied" in actions
    async with session_factory() as s:
        assert (
            await s.execute(select(PlatformUser).where(PlatformUser.email == "alice@acme.test"))
        ).scalar_one_or_none() is None


async def test_staff_and_suspended_accounts_are_refused(
    anon_client: AsyncClient, client_for: ClientFor, acme_saml: str
) -> None:
    await client_for("ops@acme.test", PlatformRole.platform_admin)
    await client_for("gone@acme.test", status=AccountStatus.suspended)
    for email, reason in (
        ("ops@acme.test", "staff_account"),
        ("gone@acme.test", "account_suspended"),
    ):
        request_id, browser, _ = await _start(anon_client)
        assert _error(await _saml_post(anon_client, request_id, browser, email=email)) == reason


async def test_login_refused_when_sso_unavailable(
    anon_client: AsyncClient, client: AsyncClient, session_factory: Factory, acme_saml: str
) -> None:
    r = await anon_client.get("/sso/nope/login")
    assert _error(r) == "sso_unavailable"
    await set_plan(session_factory, acme_saml, "team")
    assert _error(await anon_client.get("/sso/acme/login")) == "sso_unavailable"
    await set_plan(session_factory, acme_saml, "business")
    # Deactivated between the redirect and the IdP's answer.
    request_id, browser, _ = await _start(anon_client)
    await client.post("/orgs/acme/sso/deactivate")
    assert _error(await _saml_post(anon_client, request_id, browser)) == "sso_unavailable"


async def test_locked_org_refuses_sso(
    anon_client: AsyncClient, client: AsyncClient, acme_saml: str
) -> None:
    request_id, browser, _ = await _start(anon_client)
    assert (await client.delete("/orgs/acme")).status_code == 202
    assert _error(await _saml_post(anon_client, request_id, browser)) == "sso_unavailable"


async def test_garbage_post_is_a_clean_error(anon_client: AsyncClient, acme_saml: str) -> None:
    r = await anon_client.post(
        "/sso/saml/acme/acs",
        content="SAMLResponse=%%%",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert _error(r) == "malformed"
    r = await anon_client.post("/sso/saml/acme/acs", content=b"")
    assert _error(r) == "malformed"


# -- OIDC -----------------------------------------------------------------------------------


@pytest.fixture
def idp(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """A fake OIDC provider. `state["id_token"]` is what the token endpoint will return."""
    state: dict[str, object] = {"requests": []}

    async def resolve(host: str) -> list[str]:
        return ["93.184.216.34"]

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)  # type: ignore[attr-defined]
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json=discovery_document())
        if request.url.path == "/jwks":
            return httpx.Response(200, json=jwks())
        if request.url.path == "/token":
            return httpx.Response(200, json={"id_token": state["id_token"]})
        return httpx.Response(404)

    monkeypatch.setattr(oidc, "_resolve", resolve)
    monkeypatch.setattr(oidc, "TRANSPORT", httpx.MockTransport(handler))
    return state


@pytest.fixture
async def acme_oidc(
    client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],  # noqa: F811
) -> str:
    org = await business_org(client, session_factory)
    await verified_domain(client, dns)
    assert (await client.put("/orgs/acme/sso", json=OIDC_CONFIG)).status_code == 200
    assert (await client.post("/orgs/acme/sso/activate")).status_code == 200
    return org


async def test_oidc_login(
    anon_client: AsyncClient, session_factory: Factory, idp: dict[str, object], acme_oidc: str
) -> None:
    r = await anon_client.get("/sso/acme/login", params={"login_hint": "alice@acme.test"})
    assert r.status_code == 302
    location = r.headers["location"]
    assert location.startswith(OIDC_ISSUER + "/authorize?")
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(location).query))
    assert q["redirect_uri"] == "http://localhost:8000/sso/oidc/acme/callback"
    assert q["code_challenge_method"] == "S256" and q["login_hint"] == "alice@acme.test"
    browser = _cookie(r, "bb_sso")
    idp["id_token"] = id_token(
        client_id="builder-client", nonce=q["nonce"], email="alice@acme.test"
    )
    cb = await anon_client.get(
        "/sso/oidc/acme/callback",
        params={"state": q["state"], "code": "auth-code"},
        headers={"Cookie": f"bb_sso={browser}"},
    )
    assert _error(cb) is None, cb.headers["location"]
    session = await anon_client.post("/account/refresh", headers=CSRF)
    assert session.json()["user"]["email"] == "alice@acme.test"
    token_call = next(
        x
        for x in idp["requests"]
        if x.url.path == "/token"  # type: ignore[attr-defined]
    )
    form = dict(urllib.parse.parse_qsl(token_call.content.decode()))
    assert form["code"] == "auth-code" and len(form["code_verifier"]) >= 43
    member = await _member(session_factory, acme_oidc, "alice@acme.test")
    assert member is not None

    # The state is single-use.
    again = await anon_client.get(
        "/sso/oidc/acme/callback",
        params={"state": q["state"], "code": "auth-code"},
        headers={"Cookie": f"bb_sso={browser}"},
    )
    assert _error(again) == "invalid_request_state"


async def test_oidc_wrong_nonce_and_idp_errors(
    anon_client: AsyncClient, idp: dict[str, object], acme_oidc: str
) -> None:
    state, browser, _ = await _start(anon_client)
    idp["id_token"] = id_token(client_id="builder-client", nonce="replayed", email="a@acme.test")
    cb = await anon_client.get(
        "/sso/oidc/acme/callback",
        params={"state": state, "code": "c"},
        headers={"Cookie": f"bb_sso={browser}"},
    )
    assert _error(cb) == "wrong_nonce"

    state, browser, _ = await _start(anon_client)
    cb = await anon_client.get(
        "/sso/oidc/acme/callback",
        params={"state": state, "error": "access_denied"},
        headers={"Cookie": f"bb_sso={browser}"},
    )
    assert _error(cb) == "idp_error"


async def test_oidc_private_discovery_url_is_refused(
    anon_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, acme_oidc: str
) -> None:
    async def internal(host: str) -> list[str]:
        return ["169.254.169.254"]

    monkeypatch.setattr(oidc, "_resolve", internal)
    assert _error(await anon_client.get("/sso/acme/login")) == "private_address"
