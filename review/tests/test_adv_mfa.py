"""Adversarial review: MFA (REQ-§4.4): replay, recovery-code reuse, brute-force lock, challenge reuse.
Run: uv run python -m pytest review/tests/test_adv_mfa.py -p no:cacheprovider -q
"""
from tests.api._mfa_helpers import enroll
from tests.api.conftest import TEST_PASSWORD, ClientFor, TotpClock
from app.core import totp


async def _login(anon, email):  # noqa: ANN001
    r = await anon.post("/account/login", json={"email": email, "password": TEST_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()


async def test_totp_code_reuse_recovery_reuse_and_lock(client_for: ClientFor, anon_client, totp_clock: TotpClock) -> None:
    u = await client_for("mfa-adv@example.com")
    secret, recovery = await enroll(u, totp_clock)
    # 1. a valid code works once, the same code is refused the second time
    ch = await _login(anon_client, "mfa-adv@example.com")
    assert ch.get("mfa_required") is True
    code = totp.code_at(secret, totp_clock.now + 30)
    totp_clock.now += 30
    r1 = await anon_client.post("/account/login/mfa", json={"mfa_token": ch["mfa_token"], "code": code})
    assert r1.status_code == 200, r1.text
    ch2 = await _login(anon_client, "mfa-adv@example.com")
    r2 = await anon_client.post("/account/login/mfa", json={"mfa_token": ch2["mfa_token"], "code": code})
    assert r2.status_code in (401, 422), ("TOTP replay accepted", r2.status_code)
    # 2. recovery code single-use
    ch3 = await _login(anon_client, "mfa-adv@example.com")
    ok = await anon_client.post("/account/login/mfa", json={"mfa_token": ch3["mfa_token"], "code": recovery[0]})
    assert ok.status_code == 200, ok.text
    ch4 = await _login(anon_client, "mfa-adv@example.com")
    again = await anon_client.post("/account/login/mfa", json={"mfa_token": ch4["mfa_token"], "code": recovery[0]})
    assert again.status_code in (401, 422), ("recovery code reused", again.status_code)
    # recovery code case/format variants must not bypass single-use
    for variant in (recovery[0].upper(), recovery[0].replace("-", ""), " " + recovery[0] + " "):
        ch5 = await _login(anon_client, "mfa-adv@example.com") if (await anon_client.post("/account/login", json={"email": "mfa-adv@example.com", "password": TEST_PASSWORD})).status_code == 200 else None
        if ch5:
            rv = await anon_client.post("/account/login/mfa", json={"mfa_token": ch5["mfa_token"], "code": variant})
            assert rv.status_code != 200, ("used recovery code accepted in variant form", variant)


async def test_wrong_codes_lock_the_account_and_good_code_then_fails(client_for: ClientFor, anon_client, totp_clock: TotpClock) -> None:
    u = await client_for("mfa-lock@example.com")
    secret, _ = await enroll(u, totp_clock)
    ch = await _login(anon_client, "mfa-lock@example.com")
    statuses = []
    for i in range(12):
        r = await anon_client.post("/account/login/mfa", json={"mfa_token": ch["mfa_token"], "code": f"{i:06d}"})
        statuses.append(r.status_code)
    assert statuses[:4] == [401] * 4 or all(s in (401, 422, 429) for s in statuses[:5]), statuses
    # after >= login_max_failures wrong codes, even the right code must be refused for a while
    good = totp.code_at(secret, totp_clock.now + 60)
    totp_clock.now += 60
    r = await anon_client.post("/account/login/mfa", json={"mfa_token": ch["mfa_token"], "code": good})
    assert r.status_code != 200, f"locked account accepted a correct code: {statuses}"
    # re-entering the password must not reset the counter or unlock
    again = await anon_client.post("/account/login", json={"email": "mfa-lock@example.com", "password": TEST_PASSWORD})
    assert again.status_code in (401, 423, 429), again.status_code


async def test_challenge_token_is_not_a_bearer_and_wrong_surface(client_for: ClientFor, anon_client, totp_clock: TotpClock) -> None:
    u = await client_for("mfa-surf@example.com")
    secret, _ = await enroll(u, totp_clock)
    ch = await _login(anon_client, "mfa-surf@example.com")
    for p in ("/orgs", "/projects", "/account/mfa"):
        r = await anon_client.get(p, headers={"Authorization": f"Bearer {ch['mfa_token']}"})
        assert r.status_code == 401, (p, r.status_code)
    code = totp.code_at(secret, totp_clock.now + 30)
    r = await anon_client.post("/admin/login/mfa", json={"mfa_token": ch["mfa_token"], "code": code})
    assert r.status_code in (400, 401, 403, 422), ("app challenge accepted on admin surface", r.status_code)
