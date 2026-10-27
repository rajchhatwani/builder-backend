"""Built-in TOTP for every account, mandatory MFA for platform staff (§4.4 Phase 1)."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.core import platform_security as sec
from app.main import app
from app.models.enums import PlatformRole
from app.models.platform import AuditLog, MfaRecoveryCode, PlatformUser
from tests.api._mfa_helpers import admin_sign_in, enroll
from tests.api.conftest import TEST_PASSWORD, ClientFor, MakeUser, TotpClock

ADMIN = PlatformRole.platform_admin
SUPPORT = PlatformRole.platform_support


def _amr(token: str, audience: str = sec.AUDIENCE_APP) -> list[str]:
    return sec.decode_jwt(token, audience=audience).get("amr", [])


async def _login(anon: AsyncClient, email: str, password: str = TEST_PASSWORD) -> dict:
    r = await anon.post("/account/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


# -- enrolment ------------------------------------------------------------------------------


async def test_setup_then_enable_turns_totp_on(client: AsyncClient, totp_clock: TotpClock) -> None:
    status = (await client.get("/account/mfa")).json()
    assert status["totp_enabled"] is False and status["recovery_codes_left"] == 0
    assert (await client.get("/account/me")).json()["mfa_enabled"] is False

    setup = await client.post("/account/mfa/totp/setup", json={"password": TEST_PASSWORD})
    assert setup.status_code == 200
    body = setup.json()
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert body["secret"] in body["otpauth_uri"]
    # Setting up is not enabling: nothing changes until a code proves the app works.
    assert (await client.get("/account/mfa")).json()["totp_enabled"] is False

    done = await client.post(
        "/account/mfa/totp/enable", json={"code": totp_clock.code(body["secret"])}
    )
    assert done.status_code == 200
    out = done.json()
    assert len(out["recovery_codes"]) == 10
    # The new session counts as MFA'd, so an org that requires MFA works straight away.
    assert "otp" in _amr(out["access_token"])
    assert "bb_refresh=" in done.headers["set-cookie"]
    client.headers["Authorization"] = f"Bearer {out['access_token']}"
    status = (await client.get("/account/mfa")).json()
    assert status["totp_enabled"] is True and status["recovery_codes_left"] == 10
    assert (await client.get("/account/me")).json()["mfa_enabled"] is True


async def test_setup_needs_the_password_and_a_session(
    client: AsyncClient, totp_clock: TotpClock
) -> None:
    bad = await client.post("/account/mfa/totp/setup", json={"password": "wrong-password-123"})
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_password"
    token = (await client.post("/account/tokens", json={"name": "t", "scopes": ["read"]})).json()
    pat = {"Authorization": f"Bearer {token['token']}"}
    r = await client.post("/account/mfa/totp/setup", json={"password": TEST_PASSWORD}, headers=pat)
    assert r.status_code == 403 and r.json()["code"] == "session_required"


async def test_enable_refuses_a_wrong_code_without_signing_out(
    client: AsyncClient, totp_clock: TotpClock
) -> None:
    await client.post("/account/mfa/totp/setup", json={"password": TEST_PASSWORD})
    r = await client.post("/account/mfa/totp/enable", json={"code": "000000"})
    # 422, not 401: a 401 would make the app think the session ended.
    assert r.status_code == 422 and r.json()["code"] == "invalid_mfa_code"
    assert (await client.get("/account/mfa")).json()["totp_enabled"] is False


async def test_enable_without_setup_is_refused(client: AsyncClient) -> None:
    r = await client.post("/account/mfa/totp/enable", json={"code": "123456"})
    assert r.status_code == 409 and r.json()["code"] == "mfa_setup_required"


async def test_setup_twice_when_enabled_is_refused(
    client: AsyncClient, totp_clock: TotpClock
) -> None:
    await enroll(client, totp_clock)
    r = await client.post("/account/mfa/totp/setup", json={"password": TEST_PASSWORD})
    assert r.status_code == 409 and r.json()["code"] == "mfa_already_enabled"


async def test_the_secret_is_stored_encrypted_and_never_audited(
    client: AsyncClient,
    totp_clock: TotpClock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    secret, codes = await enroll(client, totp_clock)
    async with session_factory() as s:
        user = (
            await s.execute(select(PlatformUser).where(PlatformUser.email == "primary@example.com"))
        ).scalar_one()
        assert user.totp_secret_enc and secret not in user.totp_secret_enc
        stored = (await s.execute(select(MfaRecoveryCode.code_hash))).scalars().all()
        assert len(stored) == 10 and not set(codes) & set(stored)
        audit = (await s.execute(select(AuditLog))).scalars().all()
        assert "account.mfa_enabled" in {a.action for a in audit}
        blob = repr([(a.action, a.detail) for a in audit])
        assert secret not in blob and codes[0] not in blob


# -- sign-in with TOTP ----------------------------------------------------------------------


async def test_login_asks_for_a_code_then_signs_in(
    client: AsyncClient, anon_client: AsyncClient, totp_clock: TotpClock
) -> None:
    secret, _ = await enroll(client, totp_clock)
    r = await anon_client.post(
        "/account/login", json={"email": "primary@example.com", "password": TEST_PASSWORD}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["mfa_required"] is True and body["enrollment_required"] is False
    assert "access_token" not in body and "set-cookie" not in r.headers
    done = await anon_client.post(
        "/account/login/mfa", json={"mfa_token": body["mfa_token"], "code": totp_clock.code(secret)}
    )
    assert done.status_code == 200
    assert set(_amr(done.json()["access_token"])) == {"pwd", "otp"}
    assert "bb_refresh=" in done.headers["set-cookie"]
    # The refreshed token keeps the methods of the sign-in.
    again = await anon_client.post("/account/refresh", headers={"X-Requested-With": "builder"})
    assert again.status_code == 200 and "otp" in _amr(again.json()["access_token"])


async def test_a_code_is_never_accepted_twice(
    client: AsyncClient, anon_client: AsyncClient, totp_clock: TotpClock
) -> None:
    secret, _ = await enroll(client, totp_clock)
    code = totp_clock.code(secret)
    t1 = (await _login(anon_client, "primary@example.com"))["mfa_token"]
    assert (
        await anon_client.post("/account/login/mfa", json={"mfa_token": t1, "code": code})
    ).status_code == 200
    t2 = (await _login(anon_client, "primary@example.com"))["mfa_token"]
    r = await anon_client.post("/account/login/mfa", json={"mfa_token": t2, "code": code})
    assert r.status_code == 401 and r.json()["code"] == "invalid_mfa_code"


async def test_recovery_codes_work_once(
    client: AsyncClient, anon_client: AsyncClient, totp_clock: TotpClock
) -> None:
    _, codes = await enroll(client, totp_clock)
    t1 = (await _login(anon_client, "primary@example.com"))["mfa_token"]
    ok = await anon_client.post(
        "/account/login/mfa", json={"mfa_token": t1, "code": codes[0].upper().replace("-", "")}
    )
    assert ok.status_code == 200 and "rc" in _amr(ok.json()["access_token"])
    t2 = (await _login(anon_client, "primary@example.com"))["mfa_token"]
    r = await anon_client.post("/account/login/mfa", json={"mfa_token": t2, "code": codes[0]})
    assert r.status_code == 401
    headers = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    assert (await anon_client.get("/account/mfa", headers=headers)).json()[
        "recovery_codes_left"
    ] == 9


async def test_wrong_codes_lock_the_account_like_wrong_passwords(
    client: AsyncClient, anon_client: AsyncClient, totp_clock: TotpClock
) -> None:
    secret, _ = await enroll(client, totp_clock)
    settings = get_settings()
    for _ in range(settings.login_max_failures):
        token = (await _login(anon_client, "primary@example.com"))["mfa_token"]
        r = await anon_client.post(
            "/account/login/mfa", json={"mfa_token": token, "code": "000000"}
        )
        assert r.status_code == 401
    # Locked now: the password step answers the generic 401, and so does a correct code on a
    # challenge issued before the lock.
    r = await anon_client.post(
        "/account/login", json={"email": "primary@example.com", "password": TEST_PASSWORD}
    )
    assert r.status_code == 401 and r.json()["code"] == "invalid_credentials"


async def test_a_successful_password_does_not_reset_the_code_failure_count(
    client: AsyncClient, anon_client: AsyncClient, totp_clock: TotpClock
) -> None:
    """Otherwise re-entering the password would give unlimited guesses at the code."""
    await enroll(client, totp_clock)
    settings = get_settings()
    for _ in range(settings.login_max_failures - 1):
        token = (await _login(anon_client, "primary@example.com"))["mfa_token"]
        await anon_client.post("/account/login/mfa", json={"mfa_token": token, "code": "000000"})
    token = (await _login(anon_client, "primary@example.com"))["mfa_token"]
    await anon_client.post("/account/login/mfa", json={"mfa_token": token, "code": "000000"})
    r = await anon_client.post(
        "/account/login", json={"email": "primary@example.com", "password": TEST_PASSWORD}
    )
    assert r.status_code == 401


async def test_bad_or_foreign_challenge_tokens_are_refused(
    client: AsyncClient, anon_client: AsyncClient, totp_clock: TotpClock
) -> None:
    secret, _ = await enroll(client, totp_clock)
    r = await anon_client.post("/account/login/mfa", json={"mfa_token": "x.y.z", "code": "123456"})
    assert r.status_code == 401 and r.json()["code"] == "invalid_mfa_token"
    # An access token is not a challenge.
    access = client.headers["Authorization"].split()[1]
    r = await anon_client.post(
        "/account/login/mfa", json={"mfa_token": access, "code": totp_clock.code(secret)}
    )
    assert r.status_code == 401 and r.json()["code"] == "invalid_mfa_token"
    # A customer-app challenge is not good for the admin console.
    token = (await _login(anon_client, "primary@example.com"))["mfa_token"]
    r = await anon_client.post(
        "/admin/login/mfa", json={"mfa_token": token, "code": totp_clock.code(secret)}
    )
    assert r.status_code == 401 and r.json()["code"] == "invalid_mfa_token"


async def test_a_challenge_dies_when_the_password_changes(
    client: AsyncClient,
    anon_client: AsyncClient,
    totp_clock: TotpClock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    secret, _ = await enroll(client, totp_clock)
    token = (await _login(anon_client, "primary@example.com"))["mfa_token"]
    async with session_factory() as s:
        user = (
            await s.execute(select(PlatformUser).where(PlatformUser.email == "primary@example.com"))
        ).scalar_one()
        user.token_version += 1
        await s.commit()
    r = await anon_client.post(
        "/account/login/mfa", json={"mfa_token": token, "code": totp_clock.code(secret)}
    )
    assert r.status_code == 401 and r.json()["code"] == "invalid_mfa_token"


# -- turning it off, new recovery codes -----------------------------------------------------


async def test_disable_needs_password_and_code(
    client: AsyncClient, anon_client: AsyncClient, totp_clock: TotpClock
) -> None:
    secret, _ = await enroll(client, totp_clock)
    bad = await client.post(
        "/account/mfa/totp/disable", json={"password": TEST_PASSWORD, "code": "000000"}
    )
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_mfa_code"
    ok = await client.post(
        "/account/mfa/totp/disable",
        json={"password": TEST_PASSWORD, "code": totp_clock.code(secret)},
    )
    assert ok.status_code == 204
    status = (await client.get("/account/mfa")).json()
    assert status["totp_enabled"] is False and status["recovery_codes_left"] == 0
    body = await _login(anon_client, "primary@example.com")
    assert "access_token" in body  # password only again


async def test_regenerate_recovery_codes(client: AsyncClient, totp_clock: TotpClock) -> None:
    secret, old = await enroll(client, totp_clock)
    r = await client.post("/account/mfa/recovery-codes", json={"code": totp_clock.code(secret)})
    assert r.status_code == 200
    new = r.json()["recovery_codes"]
    assert len(new) == 10 and not set(new) & set(old)
    assert (await client.get("/account/mfa")).json()["recovery_codes_left"] == 10


async def test_sso_only_accounts_cannot_set_up_totp(
    client_for: ClientFor,
    totp_clock: TotpClock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """They have no password; their second factor is the IdP's job."""
    c = await client_for("sso@example.com")
    async with session_factory() as s:
        user = await s.get(PlatformUser, c.user.id)  # type: ignore[attr-defined]
        assert user is not None
        user.password_hash = sec.SSO_ONLY_PASSWORD_HASH
        await s.commit()
    r = await c.post("/account/mfa/totp/setup", json={"password": "anything-at-all-1"})
    assert r.status_code == 409 and r.json()["code"] == "sso_only_account"
    assert (await c.get("/account/mfa")).json()["sso_only"] is True


# -- platform staff: MFA at all times -------------------------------------------------------


async def test_staff_must_enroll_before_the_admin_console_signs_them_in(
    anon_client: AsyncClient, make_user: MakeUser, totp_clock: TotpClock
) -> None:
    await make_user("root@example.com", ADMIN)
    first = (
        await anon_client.post(
            "/admin/login", json={"email": "root@example.com", "password": TEST_PASSWORD}
        )
    ).json()
    assert first["mfa_required"] is True and first["enrollment_required"] is True
    assert "access_token" not in first
    # The enrolment challenge cannot be spent as a sign-in.
    r = await anon_client.post(
        "/admin/login/mfa", json={"mfa_token": first["mfa_token"], "code": "123456"}
    )
    assert r.status_code == 401 and r.json()["code"] == "invalid_mfa_token"

    token, secret = await admin_sign_in(anon_client, totp_clock, "root@example.com")
    assert set(_amr(token, sec.AUDIENCE_ADMIN)) == {"pwd", "otp"}
    h = {"Authorization": f"Bearer {token}"}
    assert (await anon_client.get("/admin/stats", headers=h)).status_code == 200
    # Second time round: a code, no enrolment.
    again = (
        await anon_client.post(
            "/admin/login", json={"email": "root@example.com", "password": TEST_PASSWORD}
        )
    ).json()
    assert again["enrollment_required"] is False
    await admin_sign_in(anon_client, totp_clock, "root@example.com", secret)


async def test_staff_also_need_mfa_on_the_customer_app(
    anon_client: AsyncClient, make_user: MakeUser, totp_clock: TotpClock
) -> None:
    await make_user("help@example.com", SUPPORT)
    body = await _login(anon_client, "help@example.com")
    assert body["mfa_required"] is True and body["enrollment_required"] is True
    setup = await anon_client.post(
        "/account/login/mfa/setup", json={"mfa_token": body["mfa_token"]}
    )
    secret = setup.json()["secret"]
    done = await anon_client.post(
        "/account/login/mfa/enable",
        json={"mfa_token": body["mfa_token"], "code": totp_clock.code(secret)},
    )
    assert done.status_code == 200 and len(done.json()["recovery_codes"]) == 10
    assert "otp" in _amr(done.json()["access_token"])


async def test_enrolment_endpoints_refuse_a_verify_challenge(
    client: AsyncClient, anon_client: AsyncClient, totp_clock: TotpClock
) -> None:
    """A person who already has TOTP cannot swap in a new authenticator with just a password."""
    await enroll(client, totp_clock)
    token = (await _login(anon_client, "primary@example.com"))["mfa_token"]
    r = await anon_client.post("/account/login/mfa/setup", json={"mfa_token": token})
    assert r.status_code == 401 and r.json()["code"] == "invalid_mfa_token"


async def test_staff_cannot_turn_mfa_off(client_for: ClientFor, totp_clock: TotpClock) -> None:
    c = await client_for("root@example.com", ADMIN)
    secret, _ = await enroll(c, totp_clock)
    r = await c.post(
        "/account/mfa/totp/disable",
        json={"password": TEST_PASSWORD, "code": totp_clock.code(secret)},
    )
    assert r.status_code == 409 and r.json()["code"] == "mfa_required_for_staff"


async def test_admin_refresh_refuses_a_session_without_mfa(
    anon_client: AsyncClient, make_user: MakeUser
) -> None:
    """A session started before MFA was mandatory (or with it switched off) ends at refresh."""
    await make_user("root@example.com", ADMIN)
    app.dependency_overrides[get_settings] = lambda: Settings(admin_mfa_required=False)
    try:
        r = await anon_client.post(
            "/admin/login", json={"email": "root@example.com", "password": TEST_PASSWORD}
        )
        assert r.status_code == 200 and "access_token" in r.json()
    finally:
        del app.dependency_overrides[get_settings]
    r = await anon_client.post("/admin/refresh", headers={"X-Requested-With": "builder"})
    assert r.status_code == 401 and r.json()["code"] == "invalid_session"


async def test_operator_can_reset_a_lost_authenticator(
    client_for: ClientFor, anon_client: AsyncClient, totp_clock: TotpClock
) -> None:
    user = await client_for("lost@example.com")
    await enroll(user, totp_clock)
    root = await client_for("root@example.com", ADMIN, audience=sec.AUDIENCE_ADMIN)
    uid = user.user.id  # type: ignore[attr-defined]
    assert (
        await root.post(f"/admin/users/{uid}/reset-mfa", json={})
    ).status_code == 422  # a reason is required
    r = await root.post(f"/admin/users/{uid}/reset-mfa", json={"reason": "ticket 42"})
    assert r.status_code == 200 and r.json()["mfa_enabled"] is False
    # Sessions die with it, and the next login is password only.
    assert (await user.get("/account/me")).status_code == 401
    assert "access_token" in await _login(anon_client, "lost@example.com")
    assert (
        await root.post(f"/admin/users/{uuid.uuid4()}/reset-mfa", json={"reason": "x"})
    ).status_code == 404


async def test_support_staff_cannot_reset_mfa(client_for: ClientFor) -> None:
    user = await client_for("lost@example.com")
    support = await client_for("help@example.com", SUPPORT, audience=sec.AUDIENCE_ADMIN)
    r = await support.post(
        f"/admin/users/{user.user.id}/reset-mfa",  # type: ignore[attr-defined]
        json={"reason": "x"},
    )
    assert r.status_code == 403


async def test_a_staff_customer_app_challenge_does_not_open_the_admin_console(
    anon_client: AsyncClient, make_user: MakeUser, totp_clock: TotpClock
) -> None:
    """The challenge names the surface it was issued for; the account checks alone would let
    a staff member's customer-app challenge through."""
    await make_user("root@example.com", ADMIN)
    _, secret = await admin_sign_in(anon_client, totp_clock, "root@example.com")
    app_challenge = (await _login(anon_client, "root@example.com"))["mfa_token"]
    r = await anon_client.post(
        "/admin/login/mfa", json={"mfa_token": app_challenge, "code": totp_clock.code(secret)}
    )
    assert r.status_code == 401 and r.json()["code"] == "invalid_mfa_token"


# -- review F-006: the admin guard itself insists on the second factor ----------------------------


async def test_admin_token_without_a_second_factor_is_refused(
    make_user, override_session  # noqa: ANN001
) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import app
    from tests.api.conftest import bearer_for

    staff = await make_user("pwd-only@example.com", PlatformRole.platform_admin)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        weak = await c.get(
            "/admin/users", headers=bearer_for(staff, sec.AUDIENCE_ADMIN, amr=["pwd"])
        )
        strong = await c.get(
            "/admin/users", headers=bearer_for(staff, sec.AUDIENCE_ADMIN, amr=["pwd", "otp"])
        )
    assert weak.status_code == 403 and weak.json()["code"] == "mfa_required", weak.text
    assert strong.status_code == 200, strong.text


async def test_admin_guard_skips_the_check_when_mfa_is_switched_off(
    make_user, override_session  # noqa: ANN001
) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.config import Settings, get_settings
    from app.main import app
    from tests.api.conftest import bearer_for

    staff = await make_user("pwd-only@example.com", PlatformRole.platform_admin)
    app.dependency_overrides[get_settings] = lambda: Settings(admin_mfa_required=False)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            r = await c.get(
                "/admin/users", headers=bearer_for(staff, sec.AUDIENCE_ADMIN, amr=["pwd"])
            )
    finally:
        app.dependency_overrides.pop(get_settings, None)
    assert r.status_code == 200, r.text
