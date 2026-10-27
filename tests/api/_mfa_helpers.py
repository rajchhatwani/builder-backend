"""Helpers for tests that sign in with built-in TOTP (§4.4)."""

from httpx import AsyncClient

from tests.api.conftest import TEST_PASSWORD, TotpClock


async def enroll(client: AsyncClient, clock: TotpClock) -> tuple[str, list[str]]:
    """Turn TOTP on for a signed-in client. Returns (secret, recovery codes)."""
    setup = await client.post("/account/mfa/totp/setup", json={"password": TEST_PASSWORD})
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    done = await client.post("/account/mfa/totp/enable", json={"code": clock.code(secret)})
    assert done.status_code == 200, done.text
    client.headers["Authorization"] = f"Bearer {done.json()['access_token']}"
    return secret, done.json()["recovery_codes"]


async def admin_sign_in(
    anon: AsyncClient, clock: TotpClock, email: str, secret: str | None = None
) -> tuple[str, str]:
    """Sign in to /admin, enrolling TOTP first when the account has none.
    Returns (access token, secret)."""
    first = await anon.post("/admin/login", json={"email": email, "password": TEST_PASSWORD})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["mfa_required"] is True
    token = body["mfa_token"]
    if body["enrollment_required"]:
        setup = await anon.post("/admin/login/mfa/setup", json={"mfa_token": token})
        assert setup.status_code == 200, setup.text
        secret = setup.json()["secret"]
        done = await anon.post(
            "/admin/login/mfa/enable", json={"mfa_token": token, "code": clock.code(secret)}
        )
    else:
        assert secret is not None
        done = await anon.post(
            "/admin/login/mfa", json={"mfa_token": token, "code": clock.code(secret)}
        )
    assert done.status_code == 200, done.text
    return done.json()["access_token"], secret
