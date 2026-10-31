"""Accounts and sessions: every behaviour promised in platform_auth_service has a test here."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api import security
from app.config import Settings, get_settings
from app.core import platform_security as sec
from app.core.ratelimit import SlidingWindowLimiter
from app.main import app
from app.models.enums import AccountStatus
from app.models.platform import AuditLog, PlatformUser, RefreshToken
from tests.api.conftest import TEST_PASSWORD, ClientFor, MakeUser, bearer_for

CSRF = {"X-Requested-With": "builder"}
GOOD = "purple-giraffe-eats-lunch"


async def register(c: AsyncClient, email: str = "new@example.com", password: str = GOOD):  # noqa: ANN201
    return await c.post(
        "/account/register", json={"email": email, "password": password, "name": "N"}
    )


async def login(c: AsyncClient, email: str = "new@example.com", password: str = GOOD):  # noqa: ANN201
    return await c.post("/account/login", json={"email": email, "password": password})


# -- registration ------------------------------------------------------------------------


async def test_register_returns_session_and_a_locked_down_cookie(anon_client: AsyncClient) -> None:
    r = await register(anon_client)
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["email"] == "new@example.com"
    assert body["user"]["platform_role"] == "customer"
    assert "password" not in r.text.lower().replace("must_change_password", "")
    assert "hash" not in r.text.lower()
    assert r.headers["cache-control"] == "no-store"
    cookie = r.headers["set-cookie"].lower()
    assert "bb_refresh=" in cookie
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/account" in cookie
    assert "refresh_token" not in body  # the refresh token is never in the body


async def test_registered_user_can_use_the_access_token(anon_client: AsyncClient) -> None:
    token = (await register(anon_client)).json()["access_token"]
    me = await anon_client.get("/account/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "new@example.com"


@pytest.mark.parametrize(
    ("email", "password", "code"),
    [
        ("not-an-email", GOOD, "invalid_email"),
        ("a@b", GOOD, "invalid_email"),
        ("new@example.com", "short", "weak_password"),
        ("new@example.com", "password1234", "weak_password"),
        ("alicewonder@example.com", "alicewonder-2024!", "weak_password"),
    ],
)
async def test_register_validation(
    anon_client: AsyncClient, email: str, password: str, code: str
) -> None:
    r = await register(anon_client, email, password)
    assert r.status_code == 422
    assert r.json()["code"] == code


async def test_register_duplicate_email_case_insensitive(anon_client: AsyncClient) -> None:
    assert (await register(anon_client, "Mixed@Example.com")).status_code == 201
    r = await register(anon_client, "mixed@example.COM")
    assert r.status_code == 409


async def test_signup_can_be_closed(anon_client: AsyncClient) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(signup_mode="closed")
    try:
        r = await register(anon_client)
    finally:
        app.dependency_overrides.pop(get_settings, None)
    assert r.status_code == 403
    assert r.json()["code"] == "signup_closed"


# -- login -------------------------------------------------------------------------------


async def test_login_failures_are_indistinguishable(
    anon_client: AsyncClient, make_user: MakeUser, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await make_user("real@example.com")
    await make_user("gone@example.com", status=AccountStatus.suspended)
    wrong_password = await login(anon_client, "real@example.com", "wrong-password-123")
    unknown = await login(anon_client, "nobody@example.com", TEST_PASSWORD)
    suspended = await login(anon_client, "gone@example.com", TEST_PASSWORD)
    assert {wrong_password.status_code, unknown.status_code, suspended.status_code} == {401}
    assert wrong_password.json() == unknown.json() == suspended.json()
    assert "set-cookie" not in wrong_password.headers


async def test_login_succeeds_and_records_last_login(
    anon_client: AsyncClient, make_user: MakeUser
) -> None:
    await make_user("real@example.com")
    r = await login(anon_client, "REAL@example.com ", TEST_PASSWORD)  # case and spaces forgiven
    assert r.status_code == 200
    assert r.json()["user"]["last_login_at"] is not None


async def test_lockout_after_repeated_failures_then_expiry(
    anon_client: AsyncClient, make_user: MakeUser, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user = await make_user("real@example.com")
    for _ in range(5):
        assert (
            await login(anon_client, "real@example.com", "wrong-password-123")
        ).status_code == 401
    # Locked: even the right password is refused. A wrong password still gets the generic
    # answer (no oracle); the right one is told why and for how long (FEAT F-6).
    still_generic = await login(anon_client, "real@example.com", "wrong-password-123")
    assert still_generic.status_code == 401
    assert still_generic.json()["code"] == "invalid_credentials"
    locked = await login(anon_client, "real@example.com", TEST_PASSWORD)
    assert locked.status_code == 429
    assert locked.json()["code"] == "account_locked"
    assert int(locked.headers["Retry-After"]) > 0
    async with session_factory() as s:
        row = await s.get(PlatformUser, user.id)
        assert row is not None and row.locked_until is not None
        await s.execute(
            update(PlatformUser)
            .where(PlatformUser.id == user.id)
            .values(locked_until=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    assert (await login(anon_client, "real@example.com", TEST_PASSWORD)).status_code == 200


async def test_successful_login_resets_the_failure_counter(
    anon_client: AsyncClient, make_user: MakeUser
) -> None:
    await make_user("real@example.com")
    for _ in range(4):
        await login(anon_client, "real@example.com", "wrong-password-123")
    assert (await login(anon_client, "real@example.com", TEST_PASSWORD)).status_code == 200
    for _ in range(4):
        await login(anon_client, "real@example.com", "wrong-password-123")
    assert (await login(anon_client, "real@example.com", TEST_PASSWORD)).status_code == 200


async def test_rate_limit_per_address(anon_client: AsyncClient) -> None:
    security._limiter = SlidingWindowLimiter(3, 60)
    codes = [
        (await login(anon_client, "x@example.com", "whatever-password")).status_code
        for _ in range(5)
    ]
    assert codes[:3] == [401, 401, 401]
    assert codes[3:] == [429, 429]
    r = await login(anon_client, "x@example.com", "whatever-password")
    assert int(r.headers["retry-after"]) >= 1


# -- tokens ------------------------------------------------------------------------------


async def test_missing_malformed_and_foreign_tokens_are_401(
    anon_client: AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user("real@example.com")
    for headers in (
        {},
        {"Authorization": "Bearer"},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer not-a-token"},
        {"Authorization": "Bearer bb_pat_abcdefghij_" + "a" * 43},
        bearer_for(user, sec.AUDIENCE_ADMIN),  # admin-audience token on the customer surface
    ):
        r = await anon_client.get("/projects", headers=headers)
        assert r.status_code == 401, headers
        assert r.headers["www-authenticate"] == "Bearer"


async def test_expired_access_token_is_401(anon_client: AsyncClient, make_user: MakeUser) -> None:
    user = await make_user("real@example.com")
    stale = sec.encode_jwt(
        sec.access_claims(
            user_id=str(user.id),
            audience=sec.AUDIENCE_APP,
            token_version=0,
            ttl_seconds=60,
            now=1_000_000,
        )
    )
    r = await anon_client.get("/projects", headers={"Authorization": f"Bearer {stale}"})
    assert r.status_code == 401


async def test_token_of_a_suspended_account_stops_working(
    anon_client: AsyncClient, make_user: MakeUser, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user = await make_user("real@example.com")
    headers = bearer_for(user)
    assert (await anon_client.get("/projects", headers=headers)).status_code == 200
    async with session_factory() as s:
        await s.execute(
            update(PlatformUser)
            .where(PlatformUser.id == user.id)
            .values(status=AccountStatus.suspended)
        )
        await s.commit()
    assert (await anon_client.get("/projects", headers=headers)).status_code == 401


async def test_token_version_bump_kills_existing_access_tokens(
    anon_client: AsyncClient, make_user: MakeUser, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user = await make_user("real@example.com")
    headers = bearer_for(user)
    async with session_factory() as s:
        await s.execute(
            update(PlatformUser).where(PlatformUser.id == user.id).values(token_version=1)
        )
        await s.commit()
    assert (await anon_client.get("/projects", headers=headers)).status_code == 401


# -- refresh rotation --------------------------------------------------------------------


async def _tokens(session_factory: async_sessionmaker[AsyncSession]) -> list[RefreshToken]:
    async with session_factory() as s:
        return list(
            (await s.execute(select(RefreshToken).order_by(RefreshToken.created_at))).scalars()
        )


async def test_refresh_rotates_and_old_token_is_spent(
    anon_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await register(anon_client)
    first_cookie = anon_client.cookies.get("bb_refresh")
    r = await anon_client.post("/account/refresh", headers=CSRF)
    assert r.status_code == 200
    assert anon_client.cookies.get("bb_refresh") != first_cookie
    rows = await _tokens(session_factory)
    # register creates a session via login; refresh adds the next link of the same family
    assert len(rows) == 2 and rows[0].family_id == rows[1].family_id and rows[0].used_at is not None


async def test_refresh_reuse_inside_grace_is_refused_but_keeps_the_session(
    anon_client: AsyncClient,
) -> None:
    await register(anon_client)
    stolen = anon_client.cookies.get("bb_refresh")
    assert (await anon_client.post("/account/refresh", headers=CSRF)).status_code == 200
    legit = anon_client.cookies.get("bb_refresh")
    anon_client.cookies.set("bb_refresh", stolen, path="/account", domain="testserver.local")
    assert (await anon_client.post("/account/refresh", headers=CSRF)).status_code == 401
    anon_client.cookies.set("bb_refresh", legit, path="/account", domain="testserver.local")
    assert (await anon_client.post("/account/refresh", headers=CSRF)).status_code == 200


async def test_refresh_reuse_after_grace_revokes_the_whole_family(
    anon_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    reg = await register(anon_client)
    access = reg.json()["access_token"]
    stolen = anon_client.cookies.get("bb_refresh")
    assert (await anon_client.post("/account/refresh", headers=CSRF)).status_code == 200
    legit = anon_client.cookies.get("bb_refresh")
    async with session_factory() as s:  # pretend the first use was a minute ago
        await s.execute(
            update(RefreshToken).values(used_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await s.commit()
    anon_client.cookies.set("bb_refresh", stolen, path="/account", domain="testserver.local")
    r = await anon_client.post("/account/refresh", headers=CSRF)
    assert r.status_code == 401
    # The legitimate chain is dead too, and so is the access token minted before.
    anon_client.cookies.set("bb_refresh", legit, path="/account", domain="testserver.local")
    assert (await anon_client.post("/account/refresh", headers=CSRF)).status_code == 401
    assert (
        await anon_client.get("/projects", headers={"Authorization": f"Bearer {access}"})
    ).status_code == 401
    async with session_factory() as s:
        actions = [a for (a,) in (await s.execute(select(AuditLog.action))).all()]
    assert "account.session_revoked" in actions


async def test_refresh_requires_csrf_header_and_known_origin(anon_client: AsyncClient) -> None:
    await register(anon_client)
    assert (await anon_client.post("/account/refresh")).status_code == 403
    r = await anon_client.post(
        "/account/refresh", headers={**CSRF, "Origin": "https://evil.example"}
    )
    assert r.status_code == 403
    r = await anon_client.post(
        "/account/refresh", headers={**CSRF, "Origin": "http://localhost:5173"}
    )
    assert r.status_code == 200


async def test_refresh_without_cookie_is_401(anon_client: AsyncClient) -> None:
    assert (await anon_client.post("/account/refresh", headers=CSRF)).status_code == 401


async def test_logout_kills_the_session(anon_client: AsyncClient) -> None:
    await register(anon_client)
    cookie = anon_client.cookies.get("bb_refresh")
    assert (await anon_client.post("/account/logout", headers=CSRF)).status_code == 204
    anon_client.cookies.set("bb_refresh", cookie, path="/account", domain="testserver.local")
    assert (await anon_client.post("/account/refresh", headers=CSRF)).status_code == 401


async def test_admin_cookie_cannot_refresh_a_customer_session(anon_client: AsyncClient) -> None:
    await register(anon_client)
    token = anon_client.cookies.get("bb_refresh")
    anon_client.cookies.set("bb_admin_refresh", token, path="/admin", domain="testserver.local")
    assert (await anon_client.post("/admin/refresh", headers=CSRF)).status_code == 401


# -- password ----------------------------------------------------------------------------


async def test_change_password_flow(anon_client: AsyncClient) -> None:
    reg = await register(anon_client)
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    wrong = await anon_client.post(
        "/account/password",
        headers=headers,
        json={"current_password": "nope-nope-nope-1", "new_password": "another-long-passphrase"},
    )
    assert wrong.status_code == 403
    weak = await anon_client.post(
        "/account/password",
        headers=headers,
        json={"current_password": GOOD, "new_password": "short"},
    )
    assert weak.status_code == 422
    same = await anon_client.post(
        "/account/password", headers=headers, json={"current_password": GOOD, "new_password": GOOD}
    )
    assert same.status_code == 422
    ok = await anon_client.post(
        "/account/password",
        headers=headers,
        json={"current_password": GOOD, "new_password": "another-long-passphrase"},
    )
    assert ok.status_code == 200
    # The old access token is dead, the new one works, and only the new password signs in.
    assert (await anon_client.get("/projects", headers=headers)).status_code == 401
    new_headers = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    assert (await anon_client.get("/projects", headers=new_headers)).status_code == 200
    assert (await login(anon_client, "new@example.com", GOOD)).status_code == 401
    assert (
        await login(anon_client, "new@example.com", "another-long-passphrase")
    ).status_code == 200


async def test_must_change_password_blocks_everything_but_the_change(
    anon_client: AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user("temp@example.com", must_change_password=True)
    headers = bearer_for(user)
    blocked = await anon_client.get("/projects", headers=headers)
    assert blocked.status_code == 403 and blocked.json()["code"] == "password_change_required"
    assert (await anon_client.get("/account/me", headers=headers)).status_code == 200
    ok = await anon_client.post(
        "/account/password",
        headers=headers,
        json={"current_password": TEST_PASSWORD, "new_password": "brand-new-passphrase-1"},
    )
    assert ok.status_code == 200
    assert ok.json()["user"]["must_change_password"] is False
    new_headers = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    assert (await anon_client.get("/projects", headers=new_headers)).status_code == 200


# -- API tokens --------------------------------------------------------------------------


async def test_api_token_lifecycle(client: AsyncClient, anon_client: AsyncClient) -> None:
    created = await client.post("/account/tokens", json={"name": "ci", "scopes": ["read"]})
    assert created.status_code == 201
    token = created.json()["token"]
    assert token.startswith("bb_pat_")
    listed = (await client.get("/account/tokens")).json()
    assert len(listed) == 1 and "token" not in listed[0] and token not in str(listed)
    pat = {"Authorization": f"Bearer {token}"}
    assert (await anon_client.get("/projects", headers=pat)).status_code == 200
    assert (await client.delete(f"/account/tokens/{created.json()['id']}")).status_code == 204
    assert (await anon_client.get("/projects", headers=pat)).status_code == 401


async def test_api_token_scopes_are_enforced(client: AsyncClient, anon_client: AsyncClient) -> None:
    project = (await client.post("/projects", json={"name": "Shop"})).json()["id"]
    read = {
        "Authorization": "Bearer "
        + (await client.post("/account/tokens", json={"name": "r", "scopes": ["read"]})).json()[
            "token"
        ]
    }
    write = {
        "Authorization": "Bearer "
        + (await client.post("/account/tokens", json={"name": "w", "scopes": ["write"]})).json()[
            "token"
        ]
    }
    entity = {"name": "Item"}
    assert (await anon_client.get(f"/projects/{project}/entities", headers=read)).status_code == 200
    denied = await anon_client.post(f"/projects/{project}/entities", headers=read, json=entity)
    assert denied.status_code == 403 and denied.json()["code"] == "insufficient_scope"
    assert (
        await anon_client.post(f"/projects/{project}/entities", headers=write, json=entity)
    ).status_code == 201
    # write does not include generate: the zip leaves the platform
    gen = await anon_client.get(f"/projects/{project}/generate/download", headers=write)
    assert gen.status_code == 403 and gen.json()["code"] == "insufficient_scope"


async def test_api_token_pinned_to_one_project(
    client: AsyncClient, anon_client: AsyncClient
) -> None:
    a = (await client.post("/projects", json={"name": "A"})).json()["id"]
    b = (await client.post("/projects", json={"name": "B"})).json()["id"]
    pinned = (
        await client.post(
            "/account/tokens", json={"name": "a-only", "scopes": ["read"], "project_id": a}
        )
    ).json()["token"]
    headers = {"Authorization": f"Bearer {pinned}"}
    assert (await anon_client.get(f"/projects/{a}", headers=headers)).status_code == 200
    assert (await anon_client.get(f"/projects/{b}", headers=headers)).status_code == 404
    listed = (await anon_client.get("/projects", headers=headers)).json()
    assert [p["id"] for p in listed["items"]] == [a]
    assert (
        await anon_client.post(
            "/projects",
            headers={
                "Authorization": "Bearer "
                + (
                    await client.post(
                        "/account/tokens", json={"name": "p", "scopes": ["write"], "project_id": a}
                    )
                ).json()["token"]
            },
            json={"name": "C"},
        )
    ).status_code == 403


async def test_api_token_cannot_manage_tokens_or_password(
    client: AsyncClient, anon_client: AsyncClient
) -> None:
    pat = {
        "Authorization": "Bearer "
        + (
            await client.post("/account/tokens", json={"name": "r", "scopes": ["write", "read"]})
        ).json()["token"]
    }
    assert (
        await anon_client.post(
            "/account/tokens", headers=pat, json={"name": "x", "scopes": ["read"]}
        )
    ).status_code == 403
    assert (await anon_client.get("/account/tokens", headers=pat)).status_code == 403
    assert (
        await anon_client.post(
            "/account/password",
            headers=pat,
            json={"current_password": TEST_PASSWORD, "new_password": "whatever-passphrase-1"},
        )
    ).status_code == 403


async def test_api_token_validation(client: AsyncClient) -> None:
    assert (
        await client.post("/account/tokens", json={"name": "x", "scopes": ["root"]})
    ).status_code == 422
    assert (
        await client.post("/account/tokens", json={"name": "x", "scopes": []})
    ).status_code == 422
    assert (
        await client.post(
            "/account/tokens", json={"name": "x", "scopes": ["read"], "expires_in_days": 4000}
        )
    ).status_code == 422


async def test_expired_api_token_is_refused(
    client: AsyncClient, anon_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    from app.models.platform import ApiToken

    token = (await client.post("/account/tokens", json={"name": "r", "scopes": ["read"]})).json()[
        "token"
    ]
    async with session_factory() as s:
        await s.execute(
            update(ApiToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    assert (
        await anon_client.get("/projects", headers={"Authorization": f"Bearer {token}"})
    ).status_code == 401


async def test_a_users_tokens_are_private(client_for: ClientFor) -> None:
    a = await client_for("a@example.com")
    b = await client_for("b@example.com")
    token_id = (await a.post("/account/tokens", json={"name": "a", "scopes": ["read"]})).json()[
        "id"
    ]
    assert (await b.get("/account/tokens")).json() == []
    assert (await b.delete(f"/account/tokens/{token_id}")).status_code == 404


# -- audit trail -------------------------------------------------------------------------


async def test_audit_log_records_events_and_never_a_secret(
    anon_client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await register(anon_client)
    await login(anon_client, "new@example.com", "wrong-password-123")
    await login(anon_client, "ghost@example.com", "ghost-secret-password")
    async with session_factory() as s:
        rows = list((await s.execute(select(AuditLog))).scalars())
    actions = {r.action for r in rows}
    assert {"account.register", "account.login", "account.login_failed"} <= actions
    dump = " ".join(str((r.action, r.actor_email, r.detail)) for r in rows)
    for secret in (GOOD, "wrong-password-123", "ghost-secret-password", "bb_rt_", "bb_pat_"):
        assert secret not in dump
    failed = [r for r in rows if r.action == "account.login_failed"]
    assert {r.result.value for r in failed} == {"denied"}
    assert any(r.actor_email == "ghost@example.com" for r in failed)  # spray visible to operators
