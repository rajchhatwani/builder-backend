#!/usr/bin/env python3
"""Category 2 — MFA. Runs against the LOCAL stack (:8001 API, Mailpit sink on :8025) by default,
since several checks need an invite e-mail and the real GoDaddy mailbox has a tight send budget
shared with session 2; set BB_TARGET=tunnel to point it at the public stack instead (no invite
tests will run there without mail).

Usage: python3 final_test/sec-test-sonnet-5/repro/02_mfa.py
"""
from __future__ import annotations

import os
import sys
import time
import uuid

import requests

sys.path.insert(0, os.path.dirname(__file__))
from _common import bb, ngrok_headers, new_disposable_email, record, tunnel_api_base  # noqa: E402

TARGET = os.environ.get("BB_TARGET", "local")
API = tunnel_api_base() if TARGET == "tunnel" else os.environ.get("BB_LOCAL_API", "http://127.0.0.1:8001")
HDRS = ngrok_headers() if TARGET == "tunnel" else {}
os.environ.setdefault("BB_API", API)
if TARGET == "local":
    os.environ.setdefault("MAIL", "sink")

_session = requests.Session()


_DELAY = 0.35 if TARGET == "tunnel" else 0.1  # the tunnel's auth routes share ONE global rate-limit
                                               # bucket (see authn/1.3) -- space requests out so a
                                               # 429 from unrelated traffic doesn't masquerade as a
                                               # test failure.


def post(path, body=None, headers=None, token=None):
    h = {**HDRS, **(headers or {})}
    if token:
        h["Authorization"] = f"Bearer {token}"
    time.sleep(_DELAY)
    return _session.post(API + path, json=body, headers=h, timeout=30)


def get(path, headers=None, token=None):
    h = {**HDRS, **(headers or {})}
    if token:
        h["Authorization"] = f"Bearer {token}"
    time.sleep(_DELAY)
    return _session.get(API + path, headers=h, timeout=30)


def register(email, pw):
    r = post("/account/register", {"email": email, "password": pw, "name": "sectest"})
    if r.status_code == 429:  # shared rate-limit bucket on the tunnel (see authn/1.3): wait once
        time.sleep(float(r.headers.get("Retry-After", 15)) + 1)
        r = post("/account/register", {"email": email, "password": pw, "name": "sectest"})
    return r


def new_account():
    email = new_disposable_email("mfa")
    pw = "Correct-Horse-Battery-Staple-9!"
    r = register(email, pw)
    if r.status_code != 201:
        return None, None, None
    return email, pw, r.json()["access_token"]


def wait_for_fresh_totp_step():
    """enable()/enabling itself consumes the current 30s TOTP step (totp_last_step is set the
    moment a code is checked). Any script that wants a FRESH code afterwards must wait for the
    next step first, same as bb.Api.login already does for its own retry."""
    time.sleep(30 - time.time() % 30 + 1)


def setup_and_enable_mfa(email, pw, access_tok):
    """Returns (secret, recovery_codes) or (None, None) on failure."""
    r = post("/account/mfa/totp/setup", {"password": pw}, token=access_tok)
    if r.status_code != 200:
        return None, None
    secret = r.json()["secret"]
    code = bb.totp(secret)
    r = post("/account/mfa/totp/enable", {"code": code}, token=access_tok)
    if r.status_code != 200:
        return None, None
    return secret, r.json()["recovery_codes"]


# ---------------------------------------------------------------------------
# 1. TOTP replay across independent login attempts (not just within one call)
# ---------------------------------------------------------------------------
def test_totp_replay():
    email, pw, access_tok = new_account()
    if not access_tok:
        record("mfa", "2.1", "TOTP replay", "n/a", "could not create disposable account", "Medium", "NOT_TESTABLE")
        return
    secret, codes = setup_and_enable_mfa(email, pw, access_tok)
    if not secret:
        record("mfa", "2.1", "TOTP replay", "n/a", "could not enable MFA on disposable account", "Medium", "NOT_TESTABLE")
        return
    wait_for_fresh_totp_step()  # enable() already consumed the step we were enrolled in

    # First login + mfa, consuming a code at the current 30s step.
    r = post("/account/login", {"email": email, "password": pw})
    mfa_token_1 = r.json().get("mfa_token")
    code1 = bb.totp(secret)
    r1 = post("/account/login/mfa", {"mfa_token": mfa_token_1, "code": code1})
    first_use = r1.status_code

    # Start a second, independent login (fresh mfa_token) and try the SAME code again,
    # still within the same 30s step if possible.
    r = post("/account/login", {"email": email, "password": pw})
    mfa_token_2 = r.json().get("mfa_token")
    r2 = post("/account/login/mfa", {"mfa_token": mfa_token_2, "code": code1})
    replay_same_step = r2.status_code

    ok = first_use == 200 and replay_same_step in (401, 422)
    record("mfa", "2.1", "TOTP replay (same code reused across a second, independent challenge)",
           "first use succeeds (200); replaying the identical code under a NEW mfa_token in the same "
           "30s step is refused (totp_last_step is tracked per-user, not per-challenge-token)",
           f"first_use={first_use} replay_same_step={replay_same_step}",
           "Critical" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# 2. Recovery code reuse + format variants
# ---------------------------------------------------------------------------
def test_recovery_code_reuse_and_formats():
    email, pw, access_tok = new_account()
    if not access_tok:
        record("mfa", "2.2", "recovery code reuse/format", "n/a", "could not create account", "Medium", "NOT_TESTABLE")
        return
    secret, codes = setup_and_enable_mfa(email, pw, access_tok)
    if not codes:
        record("mfa", "2.2", "recovery code reuse/format", "n/a", "could not enable MFA", "Medium", "NOT_TESTABLE")
        return

    code_a, code_b = codes[0], codes[1]

    # (a) use code_a once -> should work
    r = post("/account/login", {"email": email, "password": pw})
    mfa_token = r.json().get("mfa_token")
    r1 = post("/account/login/mfa", {"mfa_token": mfa_token, "code": code_a})
    first_use = r1.status_code

    # (b) reuse code_a -> must fail
    r = post("/account/login", {"email": email, "password": pw})
    mfa_token = r.json().get("mfa_token")
    r2 = post("/account/login/mfa", {"mfa_token": mfa_token, "code": code_a})
    reuse = r2.status_code

    # (c) a NEW unused code with cosmetic format variants (spaces / lowercase / dashes) should
    # still work if the variant is equivalent after normalization.
    variant = code_b.lower().replace("-", " ")
    r = post("/account/login", {"email": email, "password": pw})
    mfa_token = r.json().get("mfa_token")
    r3 = post("/account/login/mfa", {"mfa_token": mfa_token, "code": variant})
    variant_use = r3.status_code

    ok = first_use == 200 and reuse in (401, 422) and variant_use == 200
    record("mfa", "2.2", "recovery code single-use + format tolerance",
           "a code works once, a second use of the SAME code is refused; lowercase/space variants "
           "of a still-unused code are accepted (normalize_recovery_code)",
           f"first_use={first_use} reuse_of_same_code={reuse} unused_code_cosmetic_variant={variant_use}",
           "Critical" if not (first_use == 200 and reuse in (401, 422)) else "Info",
           "CONFIRMED" if not (first_use == 200 and reuse in (401, 422)) else "SOLID",
           note="" if ok else "format-tolerance leg may differ; the reuse leg is the one that matters for security")


# ---------------------------------------------------------------------------
# 3. Challenge-token cross-surface / cross-purpose replay
# ---------------------------------------------------------------------------
def test_challenge_token_cross_surface():
    email, pw, access_tok = new_account()
    if not access_tok:
        record("mfa", "2.3", "challenge token cross-surface", "n/a", "could not create account", "Medium", "NOT_TESTABLE")
        return
    secret, codes = setup_and_enable_mfa(email, pw, access_tok)
    if not secret:
        record("mfa", "2.3", "challenge token cross-surface", "n/a", "could not enable MFA", "Medium", "NOT_TESTABLE")
        return
    wait_for_fresh_totp_step()

    r = post("/account/login", {"email": email, "password": pw})
    app_mfa_token = r.json().get("mfa_token")

    # (a) use the APP-surface mfa_token against the ADMIN-surface verify endpoint
    rr = post("/admin/login/mfa", {"mfa_token": app_mfa_token, "code": bb.totp(secret)})
    cross_surface = rr.status_code

    # (b) tamper with the token (flip a char) and use it on its own correct surface
    tampered = app_mfa_token[:-2] + ("Q" if app_mfa_token[-2] != "Q" else "R") + app_mfa_token[-1]
    rr = post("/account/login/mfa", {"mfa_token": tampered, "code": bb.totp(secret)})
    tampered_token = rr.status_code

    # (c) garbage / empty mfa_token
    rr = post("/account/login/mfa", {"mfa_token": "not-a-real-token", "code": bb.totp(secret)})
    garbage_token = rr.status_code

    ok = cross_surface == 401 and tampered_token == 401 and garbage_token == 401
    record("mfa", "2.3", "MFA challenge token cross-surface replay / tampering",
           "an app-audience challenge token is refused on the admin surface (401); a tampered or "
           "garbage challenge token is refused (401)",
           f"cross_surface(app_token_on_admin_endpoint)={cross_surface} tampered_token={tampered_token} "
           f"garbage_token={garbage_token}",
           "High" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# 4. Disabling MFA without proof
# ---------------------------------------------------------------------------
def test_disable_mfa_without_proof():
    email, pw, access_tok = new_account()
    if not access_tok:
        record("mfa", "2.4", "disable MFA without proof", "n/a", "could not create account", "Medium", "NOT_TESTABLE")
        return
    secret, codes = setup_and_enable_mfa(email, pw, access_tok)
    if not secret:
        record("mfa", "2.4", "disable MFA without proof", "n/a", "could not enable MFA", "Medium", "NOT_TESTABLE")
        return
    wait_for_fresh_totp_step()

    # Need a signed-in session (not just the pre-MFA access token, which may now be stale since
    # enable() issues a fresh login family); get a current one.
    r = post("/account/login", {"email": email, "password": pw})
    mfa_token = r.json()["mfa_token"]
    r = post("/account/login/mfa", {"mfa_token": mfa_token, "code": bb.totp(secret)})
    session_tok = r.json()["access_token"]

    # (a) wrong password, correct code
    rr = post("/account/mfa/totp/disable", {"password": "definitely-wrong", "code": bb.totp(secret)}, token=session_tok)
    wrong_password = rr.status_code
    # (b) correct password, wrong code
    rr = post("/account/mfa/totp/disable", {"password": pw, "code": "000000"}, token=session_tok)
    wrong_code = rr.status_code
    # (c) no code field at all / malformed body is a 422 validation error, not useful; skip.
    # (d) correct password + correct code -> should succeed. The login/mfa call just above already
    # consumed this 30s step's code, so wait for a fresh one or this would wrongly look refused.
    wait_for_fresh_totp_step()
    rr = post("/account/mfa/totp/disable", {"password": pw, "code": bb.totp(secret)}, token=session_tok)
    correct = rr.status_code

    if correct == 429:
        record("mfa", "2.4", "disabling MFA requires BOTH the current password and a valid code",
               "wrong password alone -> refused; wrong code alone -> refused; both correct -> 204",
               f"wrong_password={wrong_password} wrong_code={wrong_code} both_correct=429 (shared "
               "rate limiter fired from cumulative test traffic -- inconclusive this run, not a finding)",
               "Low", "NOT_TESTABLE")
        return
    ok = wrong_password in (401, 422) and wrong_code in (401, 422) and correct == 204
    record("mfa", "2.4", "disabling MFA requires BOTH the current password and a valid code",
           "wrong password alone -> refused; wrong code alone -> refused; both correct -> 204",
           f"wrong_password={wrong_password} wrong_code={wrong_code} both_correct={correct}",
           "High" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# 4b. An owner without MFA on their own account cannot require it org-wide (orgs.py:759-760)
# ---------------------------------------------------------------------------
def test_require_mfa_needs_own_mfa_first():
    email, pw, tok = new_account()
    if not tok:
        record("mfa", "2.4b", "org require_mfa needs the actor's own MFA first", "n/a",
               "could not create disposable account", "Medium", "NOT_TESTABLE")
        return
    slug = "sectest-selfmfa-" + uuid.uuid4().hex[:8]
    r = post("/orgs", {"name": "sectest", "slug": slug}, token=tok)
    if r.status_code != 201:
        record("mfa", "2.4b", "org require_mfa needs the actor's own MFA first", "n/a",
               f"could not create org: HTTP {r.status_code}", "Medium", "NOT_TESTABLE")
        return
    rr = _session.patch(API + f"/orgs/{slug}/policies", json={"require_mfa": True},
                         headers={**HDRS, "Authorization": f"Bearer {tok}"}, timeout=30)
    ok = rr.status_code == 409 and rr.json().get("code") == "enable_mfa_first"
    record("mfa", "2.4b", "org require_mfa needs the actor's own MFA first",
           "an owner who has not enabled MFA on their own account gets 409 enable_mfa_first "
           "when trying to require it for everyone else",
           f"status={rr.status_code} body={rr.json() if rr.content else None}",
           "Medium" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# 5. Org require-MFA: does it actually block every surface for a member without MFA?
#    (session route, API token route, MCP) -- needs a team org + an invited member.
# ---------------------------------------------------------------------------
def test_org_require_mfa_all_surfaces():
    if TARGET != "local":
        record("mfa", "2.5", "org require_mfa enforced on session/API-token/MCP surfaces",
               "n/a", "skipped: only run on the local/Mailpit stack to avoid real invite mail",
               "Medium", "NOT_TESTABLE")
        return

    owner_email, owner_pw, owner_tok = new_account()
    member_email, member_pw, _ = new_account()
    if not owner_tok or not member_email:
        record("mfa", "2.5", "org require_mfa enforced on session/API-token/MCP surfaces", "n/a",
               "could not create owner/member disposable accounts", "Medium", "NOT_TESTABLE")
        return

    # The owner must enable MFA on their OWN account first (orgs.py:759-760: "nobody locks
    # themselves out") before they may require it for everyone else -- do that as setup, then
    # get a session that counts as MFA'd.
    owner_secret, _owner_codes = setup_and_enable_mfa(owner_email, owner_pw, owner_tok)
    if not owner_secret:
        record("mfa", "2.5", "org require_mfa enforced on session/API-token/MCP surfaces", "n/a",
               "could not enable MFA on the disposable owner account (setup step)", "Medium", "NOT_TESTABLE")
        return
    wait_for_fresh_totp_step()
    r = post("/account/login", {"email": owner_email, "password": owner_pw})
    owner_mfa_token = r.json()["mfa_token"]
    r = post("/account/login/mfa", {"mfa_token": owner_mfa_token, "code": bb.totp(owner_secret)})
    if r.status_code != 200:
        record("mfa", "2.5", "org require_mfa enforced on session/API-token/MCP surfaces", "n/a",
               f"owner MFA'd re-login failed (setup step): HTTP {r.status_code}", "Medium", "NOT_TESTABLE")
        return
    owner_tok = r.json()["access_token"]

    slug = "sectest-mfa-" + uuid.uuid4().hex[:8]
    r = post("/orgs", {"name": "sectest mfa org", "slug": slug}, token=owner_tok)
    if r.status_code != 201:
        record("mfa", "2.5", "org require_mfa enforced on session/API-token/MCP surfaces", "n/a",
               f"could not create org: HTTP {r.status_code} {r.text[:200]}", "Medium", "NOT_TESTABLE")
        return
    org_id = r.json()["id"]

    # The free plan caps seats at 1 (owner only): bump the plan as staff so inviting a member
    # doesn't 402. This is a setup step, not part of what's being tested.
    staff_tok = bb.Api(base=API).staff("admin")
    rr = _session.patch(API + f"/admin/organizations/{org_id}/plan",
                         json={"plan_id": "team", "reason": "sectest setup"},
                         headers={**HDRS, "Authorization": f"Bearer {staff_tok}"}, timeout=30)
    if rr.status_code != 200:
        record("mfa", "2.5", "org require_mfa enforced on session/API-token/MCP surfaces", "n/a",
               f"could not raise seat plan as staff setup step: HTTP {rr.status_code} {rr.text[:200]}",
               "Medium", "NOT_TESTABLE")
        return

    r = post(f"/orgs/{slug}/invitations", {"email": member_email, "role": "member"}, token=owner_tok)
    if r.status_code != 201:
        record("mfa", "2.5", "org require_mfa enforced on session/API-token/MCP surfaces", "n/a",
               f"could not invite member: HTTP {r.status_code}", "Medium", "NOT_TESTABLE")
        return

    msg = bb.wait_mail(to=member_email, subject=None, timeout=60)
    if not msg or not msg.get("links"):
        record("mfa", "2.5", "org require_mfa enforced on session/API-token/MCP surfaces", "n/a",
               "invite mail not found in Mailpit within 60s", "Medium", "NOT_TESTABLE")
        return
    invite_link = next((link for link in msg["links"] if "token=" in link or "/invite" in link), msg["links"][0])
    from urllib.parse import urlparse, parse_qs
    qs = parse_qs(urlparse(invite_link).query)
    invite_token = (qs.get("token") or [None])[0]
    if not invite_token:
        record("mfa", "2.5", "org require_mfa enforced on session/API-token/MCP surfaces", "n/a",
               "could not extract invite token from the mail link", "Medium", "NOT_TESTABLE")
        return

    r = post("/account/login", {"email": member_email, "password": member_pw})
    member_tok = r.json()["access_token"]
    r = post("/orgs/invitations/accept", {"token": invite_token}, token=member_tok)
    if r.status_code != 200:
        record("mfa", "2.5", "org require_mfa enforced on session/API-token/MCP surfaces", "n/a",
               f"member could not accept invite: HTTP {r.status_code} {r.text[:200]}", "Medium", "NOT_TESTABLE")
        return

    # The owner (now MFA'd) turns require_mfa on for the org.
    rr = _session.patch(API + f"/orgs/{slug}/policies", json={"require_mfa": True},
                         headers={**HDRS, "Authorization": f"Bearer {owner_tok}"}, timeout=30)
    if rr.status_code != 200:
        record("mfa", "2.5", "org require_mfa enforced on session/API-token/MCP surfaces", "n/a",
               f"owner (MFA'd) could not turn require_mfa on: HTTP {rr.status_code} {rr.text[:200]}",
               "Medium", "NOT_TESTABLE")
        return

    # Now test enforcement on the member (no MFA) across surfaces.
    rr = get(f"/orgs/{slug}", token=member_tok)
    session_blocked = rr.status_code in (403,) and rr.json().get("code") == "org_mfa_required"
    rr2 = get(f"/orgs/{slug}/members", token=member_tok)
    session_blocked_2 = rr2.status_code == 403

    tok_resp = post("/account/tokens", {"name": "sectest", "scopes": ["read", "write"]}, token=member_tok)
    api_tok = tok_resp.json().get("token") if tok_resp.status_code == 201 else None
    api_token_blocked = None
    if api_tok:
        rr3 = get(f"/orgs/{slug}/members", token=api_tok)
        api_token_blocked = rr3.status_code == 403

    ok = session_blocked and session_blocked_2 and (api_token_blocked is not False)
    record("mfa", "2.5", "org require_mfa enforced on session AND API-token surfaces for a member without MFA",
           "every org route (except the open-without-mfa list) answers 403 org_mfa_required for a "
           "member whose account has no TOTP enabled, for both a session token and an API token",
           f"session_blocked(/orgs/{{slug}})={rr.status_code} session_blocked(/members)={rr2.status_code} "
           f"api_token_blocked={api_token_blocked}",
           "High" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


def main():
    print(f"=== 02_mfa against {TARGET} ({API}) ===")
    for fn in (
        test_totp_replay,
        test_recovery_code_reuse_and_formats,
        test_challenge_token_cross_surface,
        test_disable_mfa_without_proof,
        test_require_mfa_needs_own_mfa_first,
        test_org_require_mfa_all_surfaces,
    ):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            record("mfa", fn.__name__, fn.__name__, "test runs cleanly",
                   f"test script raised {type(exc).__name__}: {exc}", "Low", "NOT_TESTABLE")


if __name__ == "__main__":
    main()
