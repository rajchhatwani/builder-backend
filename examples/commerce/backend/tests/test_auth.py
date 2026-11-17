"""Smoke tests for authentication (generated). Email and SMS go to an in-memory outbox."""

import base64

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from httpx import AsyncClient
from sqlalchemy import text

from app.auth import config, security
from app.auth.ratelimit import parse_limit
from app.auth.router import _login_limit
from app.auth.service import effective_roles
from app.db import engine
from tests._auth_support import (
    EMAIL,
    PASSWORD,
    Outbox,
    bearer,
    extra,
    other_key,
    registration_payload,
)

# The `outbox` fixture (tests/_auth_support.py) sets the test secrets and captures mail / SMS.
pytestmark = pytest.mark.usefixtures("outbox")


async def _register(client: AsyncClient, email: str = EMAIL) -> dict[str, object]:
    payload = await registration_payload(email)
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def _register_and_verify(client: AsyncClient, box: Outbox) -> dict[str, object]:
    user = await _register(client)
    response = await client.post("/auth/email/verify", json={"token": box.link_token()})
    assert response.status_code == 200, response.text
    user = response.json()
    return user


async def _login(client: AsyncClient, password: str = PASSWORD) -> dict[str, str]:
    response = await client.post("/auth/login", json={"email": EMAIL, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


async def test_register_login_refresh_logout(client: AsyncClient, outbox: Outbox) -> None:
    user = await _register(client)
    assert "password" not in user and "password_hash" not in user
    assert user["email"] == EMAIL
    # Signing up without an invitation creates a tenant, and its creator is the admin.
    assert user["roles"] == [*config.DEFAULT_ROLES, config.ADMIN_ROLE]
    assert user['display_name'] == extra()['display_name']
    assert user['job_title'] == extra()['job_title']
    assert user['locale'] == extra()['locale']
    assert user['marketing_opt_in'] == extra()['marketing_opt_in']

    duplicate_payload = await registration_payload(EMAIL, 1)
    duplicate = await client.post("/auth/register", json=duplicate_payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "conflict"

    blocked = await client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "email_not_verified"
    assert len(outbox.emails) == 1 and outbox.emails[0][0] == EMAIL

    bad_token = await client.post("/auth/email/verify", json={"token": "not.a-token"})
    assert bad_token.status_code == 400
    verified = await client.post("/auth/email/verify", json={"token": outbox.link_token()})
    assert verified.status_code == 200, verified.text
    assert verified.json()["email_verified_at"] is not None
    reused = await client.post("/auth/email/verify", json={"token": outbox.link_token()})
    assert reused.status_code == 400

    tokens = await _login(client)
    me = await client.get("/auth/me", headers=bearer(tokens["access_token"]))
    assert me.status_code == 200, me.text
    assert me.json()["email"] == EMAIL
    assert (await client.get("/auth/me")).status_code == 401
    assert (await client.get("/auth/me", headers=bearer("a.b.c"))).status_code == 401

    rotated = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert rotated.status_code == 200, rotated.text
    new_tokens = rotated.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"]

    # Presenting the already-rotated token is treated as theft: the whole chain dies.
    replay = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert replay.status_code == 401
    after_replay = await client.post(
        "/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]}
    )
    assert after_replay.status_code == 401

    fresh = await _login(client)
    assert (
        await client.post("/auth/logout", json={"refresh_token": fresh["refresh_token"]})
    ).status_code == 204
    gone = await client.post("/auth/refresh", json={"refresh_token": fresh["refresh_token"]})
    assert gone.status_code == 401


async def test_wrong_password_and_unknown_account_are_indistinguishable(
    client: AsyncClient, outbox: Outbox
) -> None:
    await _register_and_verify(client, outbox)

    wrong = await client.post("/auth/login", json={"email": EMAIL, "password": "nope-nope-nope"})
    unknown = await client.post(
        "/auth/login", json={"email": "ghost@example.com", "password": PASSWORD}
    )

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


async def test_expired_or_forged_access_tokens_are_rejected(
    client: AsyncClient, outbox: Outbox
) -> None:
    await _register_and_verify(client, outbox)
    tokens = await _login(client)
    secret = config.get_auth_settings().jwt_key
    claims = security.decode_jwt(tokens["access_token"], secret)

    expired = security.encode_jwt({**claims, "exp": 1}, secret)
    forged = security.encode_jwt(claims, other_key())
    wrong_type = security.encode_jwt({**claims, "type": "refresh"}, secret)

    for token in (expired, forged, wrong_type):
        response = await client.get("/auth/me", headers=bearer(token))
        assert response.status_code == 401, token


async def test_change_password_signs_out_everywhere(client: AsyncClient, outbox: Outbox) -> None:
    await _register_and_verify(client, outbox)
    tokens = await _login(client)

    wrong = await client.post(
        "/auth/change-password",
        headers=bearer(tokens["access_token"]),
        json={"current_password": "wrong-wrong", "new_password": "a brand new password"},
    )
    assert wrong.status_code == 401
    changed = await client.post(
        "/auth/change-password",
        headers=bearer(tokens["access_token"]),
        json={"current_password": PASSWORD, "new_password": "a brand new password"},
    )
    assert changed.status_code == 204

    refresh = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh.status_code == 401
    login = await client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert login.status_code == 401
    assert (await _login(client, "a brand new password"))["access_token"]


async def test_delete_account(client: AsyncClient, outbox: Outbox) -> None:
    await _register_and_verify(client, outbox)
    tokens = await _login(client)

    deleted = await client.delete("/auth/me", headers=bearer(tokens["access_token"]))
    assert deleted.status_code == 204

    assert (await client.get("/auth/me", headers=bearer(tokens["access_token"]))).status_code == 401
    login = await client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert login.status_code == 401
    refresh = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh.status_code == 401


async def test_validation_errors_use_the_standard_error_body(client: AsyncClient) -> None:
    weak = await client.post("/auth/register", json={"email": "not-an-email", "password": "short"})
    assert weak.status_code == 422
    assert weak.json()["code"] == "validation_error"

    extra = await client.post(
        "/auth/login", json={"email": EMAIL, "password": PASSWORD, "admin": True}
    )
    assert extra.status_code == 422


async def test_login_is_rate_limited(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    allowed, _ = parse_limit(config.LOGIN_RATE_LIMIT)
    if allowed > 25:
        pytest.skip(f"login limit {config.LOGIN_RATE_LIMIT} is too high to exhaust in a smoke test")
    monkeypatch.setattr(_login_limit, "count", allowed)
    body = {"email": EMAIL, "password": "nope-nope-nope"}

    for _ in range(allowed):
        assert (await client.post("/auth/login", json=body)).status_code == 401
    limited = await client.post("/auth/login", json=body)

    assert limited.status_code == 429
    assert limited.json()["code"] == "rate_limited"


async def test_security_headers_are_set(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert (await client.post("/auth/login", json={})).headers["cache-control"] == "no-store"


def test_role_admin_inherits_manager() -> None:
    assert 'manager' in effective_roles(['admin'])
    assert 'admin' not in effective_roles(['manager'])


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


async def test_jwks_publishes_the_key_that_verifies_access_tokens(
    client: AsyncClient, outbox: Outbox
) -> None:
    await _register_and_verify(client, outbox)
    tokens = await _login(client)

    keys = (await client.get("/auth/jwks.json")).json()["keys"]

    assert len(keys) == 1
    assert keys[0]["alg"] == "RS256" and "d" not in keys[0], "only the public half is published"
    numbers = rsa.RSAPublicNumbers(
        int.from_bytes(_unb64(keys[0]["e"]), "big"), int.from_bytes(_unb64(keys[0]["n"]), "big")
    )
    header, payload, signature = tokens["access_token"].split(".")
    numbers.public_key().verify(
        _unb64(signature), f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256()
    )


async def test_refresh_tokens_live_in_redis_not_in_the_database(
    client: AsyncClient, outbox: Outbox
) -> None:
    await _register_and_verify(client, outbox)
    tokens = await _login(client)

    async with engine.connect() as connection:
        table = await connection.execute(text("SELECT to_regclass('auth_refresh_tokens')"))
    assert table.scalar_one() is None

    rotated = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert rotated.status_code == 200, rotated.text
    replay = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert replay.status_code == 401
    # The replay revoked the family, so the replacement stopped working too.
    successor = await client.post(
        "/auth/refresh", json={"refresh_token": rotated.json()["refresh_token"]}
    )
    assert successor.status_code == 401
