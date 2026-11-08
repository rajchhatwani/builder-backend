"""Tests for identities, sessions and account export / import (generated).

The user id is the app's own; a token only names an identity (issuer + subject) that points at it."""

import io
import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.auth import config, export, identity, security
from app.auth.models import AuthIdentity, AuthSession, AuthUser
from app.db import engine, session_factory
from tests._auth_support import PASSWORD, bearer, sign_in

pytestmark = pytest.mark.usefixtures("outbox")


def _claims(headers: dict[str, str]) -> dict[str, object]:
    return security.decode_jwt(headers["Authorization"].split()[1], config.get_auth_settings().jwt_key)


async def _user(email: str) -> AuthUser:
    async with session_factory() as session:
        return (await session.execute(select(AuthUser).where(AuthUser.email == email))).scalar_one()


async def test_registering_links_an_identity_and_tokens_carry_issuer_and_session(
    client: AsyncClient,
) -> None:
    headers = await sign_in(client, "ident@example.com")
    claims = _claims(headers)
    user = await _user("ident@example.com")
    assert claims["iss"] == config.ISSUER and claims["sub"] == str(user.id) and claims["sid"]
    async with session_factory() as session:
        row = (
            await session.execute(select(AuthIdentity).where(AuthIdentity.user_id == user.id))
        ).scalar_one()
        live = await identity.session_is_live(session, config.ISSUER, str(claims["sid"]))
    assert (row.issuer, row.subject, row.provider) == (config.ISSUER, str(user.id), "builtin")
    assert live


async def test_the_user_is_found_through_the_identity_not_the_subject(client: AsyncClient) -> None:
    headers = await sign_in(client, "moved@example.com")
    user = await _user("moved@example.com")
    forged = security.create_access_token(
        user.id, ["member"], key=config.get_auth_settings().jwt_key, ttl_seconds=60,
        issuer="builtin:somewhere-else",
    )
    refused = await client.get("/auth/me", headers=bearer(forged))
    assert refused.status_code == 401
    # Point the identity at a different subject: the old token no longer finds anyone.
    async with session_factory() as session:
        row = (
            await session.execute(select(AuthIdentity).where(AuthIdentity.user_id == user.id))
        ).scalar_one()
        row.subject = "someone-else"
        await session.commit()
    assert (await client.get("/auth/me", headers=headers)).status_code == 401


async def test_logging_out_ends_the_session_and_its_access_tokens(client: AsyncClient) -> None:
    await sign_in(client, "bye@example.com")
    login = await client.post("/auth/login", json={"email": "bye@example.com", "password": PASSWORD})
    tokens = login.json()
    assert (await client.get("/auth/me", headers=bearer(tokens["access_token"]))).status_code == 200
    out = await client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert out.status_code == 204
    assert (await client.get("/auth/me", headers=bearer(tokens["access_token"]))).status_code == 401
    async with session_factory() as session:
        ended = (
            await session.execute(select(AuthSession).where(AuthSession.revoked_at.is_not(None)))
        ).scalars().all()
    assert len(ended) == 1


async def test_relinking_an_issuer_keeps_every_local_user_id(client: AsyncClient) -> None:
    await sign_in(client, "stay@example.com")
    before = (await _user("stay@example.com")).id
    async with session_factory() as session:
        assert await identity.relink_issuer(session, config.ISSUER, "https://new.example/realms/x") == 1
    async with session_factory() as session:
        row = (await session.execute(select(AuthIdentity))).scalar_one()
        assert row.issuer == "https://new.example/realms/x" and row.user_id == before
        with pytest.raises(ValueError):
            await identity.relink_issuer(session, "builtin:nobody", row.issuer)  # the new issuer already has identities
    assert (await _user("stay@example.com")).id == before


def _body(records: list[dict[str, object]]) -> list[dict[str, object]]:
    return records[1:]  # the header holds the export time


async def _wipe() -> None:
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE auth_users, auth_tenants CASCADE"))


async def test_export_then_import_restores_identical_accounts_and_logins(client: AsyncClient) -> None:
    await sign_in(client, "one@example.com")
    await sign_in(client, "two@example.com", n=1)
    first = await export.export_records(include_hashes=True)
    assert first[0]["format"] == "identity-v1" and first[0]["includes_credentials"] is True
    assert {r.get("type") for r in first} >= {"user", "identity", "credential"}

    await _wipe()
    out = io.StringIO()
    export.write_records(first, out)
    counts = await export.import_records(out.getvalue().splitlines())
    assert counts["user"] == 2 and counts["identity"] == 2

    assert _body(await export.export_records(include_hashes=True)) == _body(first)
    again = await export.import_records(out.getvalue().splitlines())
    assert again["user"] == 0 and again["identity"] == 0  # importing twice changes nothing
    login = await client.post("/auth/login", json={"email": "one@example.com", "password": PASSWORD})
    assert login.status_code == 200, login.text


async def test_export_leaves_out_password_hashes_unless_asked(client: AsyncClient) -> None:
    await sign_in(client, "plain@example.com")
    records = await export.export_records(include_hashes=False)
    text_out = json.dumps(records)
    assert records[0]["includes_credentials"] is False
    assert "credential" not in {r.get("type") for r in records}
    assert "password_hash" not in text_out and "scrypt" not in text_out


async def test_an_import_without_hashes_creates_accounts_nobody_can_log_into(
    client: AsyncClient,
) -> None:
    await sign_in(client, "nohash@example.com")
    records = await export.export_records(include_hashes=False)
    await _wipe()
    out = io.StringIO()
    export.write_records(records, out)
    await export.import_records(out.getvalue().splitlines())
    login = await client.post("/auth/login", json={"email": "nohash@example.com", "password": PASSWORD})
    assert login.status_code == 401


async def test_an_import_refuses_other_formats(client: AsyncClient) -> None:
    with pytest.raises(ValueError):
        await export.import_records(['{"format":"something-else"}'])
    with pytest.raises(ValueError):
        await export.import_records(['{"format":"identity-v1"}', '{"type":"mystery"}'])


async def test_a_new_identity_is_never_linked_by_e_mail_by_default() -> None:
    decision = await identity.HOOKS.resolve_identity({"email": "a@example.com", "email_verified": False})
    assert decision.action == "create"


def test_subjects_are_any_short_printable_text() -> None:
    assert identity.subject_is_valid("auth0|abc123") and identity.subject_is_valid(str(uuid.uuid4()))
    assert not identity.subject_is_valid("") and not identity.subject_is_valid("x" * 256)
    assert not identity.subject_is_valid("bad\x00subject") and not identity.subject_is_valid(5)
