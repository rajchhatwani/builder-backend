"""Tests for identities, sessions, hooks and account export / import with Keycloak (generated).

A Keycloak subject is Keycloak's own id for a person. It is never this app's user id: tokens find
the user through `auth_identities`, so any subject works and the identity provider can change."""

import io
import json
import time
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.auth import config, export, identity
from app.auth.models import AuthIdentity, AuthSession, AuthUser
from app.db import engine, session_factory
from tests import _auth_support as support
from tests._auth_support import bearer, claims, sign, token

pytestmark = pytest.mark.usefixtures("key_server")

EVENT = "http://schemas.openid.net/event/backchannel-logout"


@pytest.fixture(autouse=True)
def _default_hooks() -> None:
    identity.HOOKS = identity.Hooks()


async def _identity_rows() -> list[AuthIdentity]:
    async with session_factory() as session:
        return list((await session.execute(select(AuthIdentity))).scalars())


async def test_a_subject_that_is_not_a_uuid_signs_in_with_a_stable_local_id(client: AsyncClient) -> None:
    first = await client.get("/auth/me", headers=bearer(token(sub="auth0|65f2a9")))
    again = await client.get("/auth/me", headers=bearer(token(sub="auth0|65f2a9")))
    assert first.status_code == 200, first.text
    assert again.json()["id"] == first.json()["id"]
    uuid.UUID(first.json()["id"])  # a real UUID, derived by the app
    other = await client.get("/auth/me", headers=bearer(token(sub="auth0|someone-else")))
    assert other.json()["id"] != first.json()["id"]
    rows = await _identity_rows()
    assert {r.subject for r in rows} == {"auth0|65f2a9", "auth0|someone-else"}
    assert all(r.issuer == support.issuer() and r.provider == "keycloak" for r in rows)


async def test_a_uuid_subject_keeps_its_id_unless_that_id_is_taken(client: AsyncClient) -> None:
    sub = uuid.uuid4()
    assert (await client.get("/auth/me", headers=bearer(token(sub=sub)))).json()["id"] == str(sub)
    # Another issuer's person whose subject equals an existing local id must not become that user.
    async with session_factory() as session:
        taken = await session.get(AuthUser, sub)
        assert taken is not None
        derived = identity.derived_user_id("https://other.test/realms/x", str(sub))
        assert derived != sub


@pytest.mark.parametrize("subject", ["x" * 256, "tab\there", "nul\x00byte"])
async def test_unusable_subjects_are_refused(client: AsyncClient, subject: str) -> None:
    response = await client.get("/auth/me", headers=bearer(sign(claims(sub=subject))))
    assert response.status_code == 401


async def test_the_same_person_is_one_user_however_many_requests_arrive_at_once(
    client: AsyncClient,
) -> None:
    import asyncio

    headers = bearer(token(sub="saml|racing"))
    results = await asyncio.gather(*(client.get("/auth/me", headers=headers) for _ in range(6)))
    assert {r.status_code for r in results} == {200}
    assert len({r.json()["id"] for r in results}) == 1
    assert len([r for r in await _identity_rows() if r.subject == "saml|racing"]) == 1


async def test_a_hook_can_refuse_a_new_identity_and_a_crashing_hook_fails_closed(
    client: AsyncClient,
) -> None:
    async def refuse(_claims: dict[str, object]) -> identity.LinkDecision:
        return identity.LinkDecision("reject", reason="not on the allow list")

    identity.HOOKS.resolve_identity = refuse
    assert (await client.get("/auth/me", headers=bearer(token(sub="blocked-1")))).status_code == 401

    async def explode(_claims: dict[str, object]) -> identity.LinkDecision:
        raise RuntimeError("hook bug")

    identity.HOOKS.resolve_identity = explode
    assert (await client.get("/auth/me", headers=bearer(token(sub="blocked-2")))).status_code == 401
    assert await _identity_rows() == []


async def test_a_hook_can_link_a_new_identity_to_an_existing_user(client: AsyncClient) -> None:
    existing = (await client.get("/auth/me", headers=bearer(token(sub="first-login")))).json()["id"]

    async def link(_claims: dict[str, object]) -> identity.LinkDecision:
        return identity.LinkDecision("link", user_id=uuid.UUID(existing))

    identity.HOOKS.resolve_identity = link
    second = await client.get("/auth/me", headers=bearer(token(sub="second-login", email="b@example.com")))
    assert second.json()["id"] == existing
    assert len(await _identity_rows()) == 2


async def test_on_user_provisioned_runs_once_and_a_failure_undoes_the_sign_up(client: AsyncClient) -> None:
    seen: list[identity.Principal] = []

    async def record(principal: identity.Principal) -> None:
        seen.append(principal)

    identity.HOOKS.on_user_provisioned = record
    for _ in range(2):
        assert (await client.get("/auth/me", headers=bearer(token(sub="p-1")))).status_code == 200
    assert len(seen) == 1 and seen[0].subject == "p-1" and seen[0].issuer == support.issuer()

    async def fail(_principal: identity.Principal) -> None:
        raise RuntimeError("downstream is down")

    identity.HOOKS.on_user_provisioned = fail
    assert (await client.get("/auth/me", headers=bearer(token(sub="p-2")))).status_code == 401
    assert "p-2" not in {r.subject for r in await _identity_rows()}


async def test_roles_follow_the_provider_only_while_it_is_the_master(client: AsyncClient) -> None:
    sub = "role-source-1"
    role = next(iter(config.ROLE_PARENTS))
    await client.get("/auth/me", headers=bearer(token(sub=sub, roles=[role])))
    async with session_factory() as session:
        user = (await session.execute(select(AuthUser).where(AuthUser.email == support.EMAIL))).scalar_one()
        assert user.role_source == "idp"
        user.role_source = "local"
        user.roles = []
        await session.commit()
    body = (await client.get("/auth/me", headers=bearer(token(sub=sub, roles=[role])))).json()
    assert body["roles"] == []  # an app-mastered user keeps the roles set here


async def test_a_sign_in_that_was_ended_is_refused_even_with_a_valid_token(client: AsyncClient) -> None:
    access = token(sub="sid-user", sid="session-1")
    assert (await client.get("/auth/me", headers=bearer(access))).status_code == 200
    async with session_factory() as session:
        assert await identity.end_session(session, support.issuer(), "session-1", "test") == 1
    assert (await client.get("/auth/me", headers=bearer(access))).status_code == 401
    assert (await client.get("/auth/me", headers=bearer(token(sub="sid-user", sid="session-2")))).status_code == 200


def _logout_token(**overrides: object) -> str:
    now = int(time.time())
    payload: dict[str, object] = {
        "iss": support.issuer(),
        "aud": config.WEB_CLIENT_ID,
        "iat": now,
        "jti": uuid.uuid4().hex,
        "sid": "session-1",
        "events": {EVENT: {}},
    }
    payload.update(overrides)
    return sign({k: v for k, v in payload.items() if v is not None})


async def _post_logout(client: AsyncClient, logout_token: str) -> int:
    response = await client.post(
        "/auth/backchannel-logout",
        content=f"logout_token={logout_token}",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    return response.status_code


async def test_back_channel_logout_is_off_until_enabled(client: AsyncClient) -> None:
    assert await _post_logout(client, _logout_token()) == 404


async def test_back_channel_logout_ends_the_session_it_names(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTH_BACKCHANNEL_LOGOUT_ENABLED", "true")
    config.get_auth_settings.cache_clear()
    access = token(sub="bc-user", sid="session-1")
    other = token(sub="bc-user", sid="session-keep")
    assert (await client.get("/auth/me", headers=bearer(access))).status_code == 200
    assert (await client.get("/auth/me", headers=bearer(other))).status_code == 200

    assert await _post_logout(client, _logout_token()) == 204
    assert (await client.get("/auth/me", headers=bearer(access))).status_code == 401
    assert (await client.get("/auth/me", headers=bearer(other))).status_code == 200

    # Without a sid, every session of that subject at that issuer ends.
    assert await _post_logout(client, _logout_token(sid=None, sub="bc-user")) == 204
    assert (await client.get("/auth/me", headers=bearer(other))).status_code == 401
    async with session_factory() as session:
        live = (
            await session.execute(select(AuthSession).where(AuthSession.revoked_at.is_(None)))
        ).scalars().all()
    assert live == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://evil.test/realms/x"},
        {"aud": "someone-elses-client"},
        {"events": {}},
        {"events": None},
        {"nonce": "n"},  # an ID token, not a logout token
        {"jti": None},
        {"sid": None},  # neither sid nor sub
        {"iat": 1},
    ],
)
async def test_back_channel_logout_refuses_bad_tokens(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, overrides: dict[str, object]
) -> None:
    monkeypatch.setenv("AUTH_BACKCHANNEL_LOGOUT_ENABLED", "true")
    config.get_auth_settings.cache_clear()
    assert await _post_logout(client, _logout_token(**overrides)) == 400


async def test_back_channel_logout_refuses_a_forged_signature_and_garbage(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTH_BACKCHANNEL_LOGOUT_ENABLED", "true")
    config.get_auth_settings.cache_clear()
    forged = sign(
        {"iss": support.issuer(), "aud": config.WEB_CLIENT_ID, "iat": int(time.time()), "jti": "j",
         "sid": "s", "events": {EVENT: {}}},
        key=support.other_key(),
    )
    assert await _post_logout(client, forged) == 400
    assert await _post_logout(client, "not-a-token") == 400
    empty = await client.post("/auth/backchannel-logout", content=b"", headers={"content-type": "application/x-www-form-urlencoded"})
    assert empty.status_code == 400


async def test_relinking_an_issuer_keeps_the_user_and_the_rows_they_own(client: AsyncClient) -> None:
    before = (await client.get("/auth/me", headers=bearer(token(sub="mover")))).json()["id"]
    moved = "https://new-id.test/realms/other"
    async with session_factory() as session:
        assert await identity.relink_issuer(session, support.issuer(), moved) == 1
    rows = await _identity_rows()
    assert [(r.issuer, str(r.user_id)) for r in rows] == [(moved, before)]
    async with session_factory() as session:
        assert await session.get(AuthUser, uuid.UUID(before)) is not None


async def _wipe() -> None:
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE auth_users, auth_tenants CASCADE"))


async def test_export_then_import_restores_identical_accounts(client: AsyncClient) -> None:
    await client.get("/auth/me", headers=bearer(token(sub="e-1", email="e1@example.com")))
    await client.get("/auth/me", headers=bearer(token(sub=str(uuid.uuid4()), email="e2@example.com")))
    first = await export.export_records(include_hashes=True)
    assert first[0]["format"] == "identity-v1" and first[0]["includes_credentials"] is False
    assert "credential" not in {r.get("type") for r in first}  # Keycloak keeps the passwords
    await _wipe()
    out = io.StringIO()
    export.write_records(first, out)
    counts = await export.import_records(out.getvalue().splitlines())
    assert counts["user"] == 2 and counts["identity"] == 2
    assert (await export.export_records(include_hashes=True))[1:] == first[1:]
    assert json.loads(out.getvalue().splitlines()[0])["format"] == "identity-v1"
    # The imported identity still signs the person in as the same local user.
    again = await client.get("/auth/me", headers=bearer(token(sub="e-1", email="e1@example.com")))
    assert again.status_code == 200 and again.json()["email"] == "e1@example.com"


async def test_the_principal_has_no_raw_claims() -> None:
    fields = {f.name for f in identity.dataclasses.fields(identity.Principal)}
    assert fields == {
        "user_id", "issuer", "subject", "tenant_id", "tenant_external_ref", "roles",
        "session_id", "auth_time",
    }
