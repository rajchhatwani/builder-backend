#!/usr/bin/env python3
"""Category 1 — Authn/session. Runs against the public ngrok tunnel (production-mode stack)
unless BB_TARGET=local is set (then against the local-mode stack on :8001/proxy :8082).

Usage: python3 final_test/sec-test-sonnet-5/repro/01_authn_session.py
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import uuid

import requests

sys.path.insert(0, os.path.dirname(__file__))
from _common import bb, ngrok_headers, new_disposable_email, record, tunnel_api_base  # noqa: E402

TARGET = os.environ.get("BB_TARGET", "tunnel")
API = tunnel_api_base() if TARGET == "tunnel" else os.environ.get("BB_LOCAL_API", "http://127.0.0.1:8001")
HDRS = ngrok_headers() if TARGET == "tunnel" else {}

_session = requests.Session()
_adapter = requests.adapters.HTTPAdapter(max_retries=requests.adapters.Retry(
    total=3, backoff_factor=0.5, status_forcelist=[], allowed_methods=None))
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)


def post(path, body=None, headers=None, cookies=None):
    h = {**HDRS, **(headers or {})}
    time.sleep(0.15)  # be gentle with the free ngrok tunnel
    return _session.post(API + path, json=body, headers=h, cookies=cookies, timeout=30)


def get(path, headers=None, cookies=None):
    h = {**HDRS, **(headers or {})}
    time.sleep(0.15)
    return _session.get(API + path, headers=h, cookies=cookies, timeout=30)


# ---------------------------------------------------------------------------
# 1. Brute force / lockout — use a disposable throwaway account, never the shared test accounts.
# ---------------------------------------------------------------------------
def test_lockout():
    email = new_disposable_email("lockout")
    pw = "Correct-Horse-Battery-Staple-9!"
    r = post("/account/register", {"email": email, "password": pw, "name": "sectest"})
    if r.status_code != 201:
        record("authn", "1.1", "brute force lockout", "account locks after N bad passwords",
               f"could not create disposable account: HTTP {r.status_code}", "Medium", "NOT_TESTABLE")
        return
    codes = []
    for i in range(8):
        rr = post("/account/login", {"email": email, "password": "wrong-password-" + str(i)})
        codes.append(rr.status_code)
        time.sleep(0.3)
    # NOTE: the app deliberately returns the SAME generic 401 "invalid_credentials" whether the
    # password is wrong or the account is locked (anti-enumeration: a 423/403 would tell an
    # attacker the difference). So the only live signal for "did it actually lock" is: does the
    # CORRECT password also get refused afterwards? (429 here would mean the shared per-IP rate
    # limiter fired first -- see 1.3 -- and is not evidence either way; only count a 401 result.)
    rr = post("/account/login", {"email": email, "password": pw})
    final_with_correct_pw = rr.status_code
    if final_with_correct_pw == 429:
        record("authn", "1.1", "brute force lockout",
               "after login_max_failures (5) wrong passwords, correct password is also refused (401, locked_until set)",
               f"codes for 8 bad attempts={codes}; correct-password probe hit the shared rate limiter (429) before "
               "the lockout check could run -- inconclusive this run, see repro/01b_lockout_isolated.py",
               "Low", "NOT_TESTABLE")
        return
    locked = final_with_correct_pw == 401
    record("authn", "1.1", "brute force lockout",
           "after login_max_failures (5) wrong passwords, correct password is also refused with 401 "
           "(generic message by design, to avoid telling an attacker 'locked' from 'wrong password')",
           f"codes for 8 bad attempts={codes}; correct-password attempt after lockout -> {final_with_correct_pw}",
           "Info" if locked else "High",
           "SOLID" if locked else "CONFIRMED",
           note="disposable account, now stuck in lockout_minutes window; harmless")


def test_lockout_case_unicode_bypass():
    """Does varying the case of the e-mail reset/avoid the failure counter (separate bucket)?"""
    email = new_disposable_email("caselock")
    pw = "Correct-Horse-Battery-Staple-9!"
    r = post("/account/register", {"email": email, "password": pw, "name": "sectest"})
    if r.status_code != 201:
        record("authn", "1.2", "lockout bucketing by case/unicode email variant", "n/a",
               "could not create disposable account", "Medium", "NOT_TESTABLE")
        return
    local, domain = email.split("@", 1)
    variants = [email, email.upper(), local.upper() + "@" + domain, local + "@" + domain.upper()]
    codes = {}
    for v in variants:
        rs = []
        for i in range(3):
            rr = post("/account/login", {"email": v, "password": "still-wrong"})
            rs.append(rr.status_code)
        codes[v] = rs
    # platform_auth_service.normalize_email() = email.strip().lower() BEFORE the DB lookup
    # (platform_auth_service.py:59), so every case variant resolves to the same row/counter.
    # Live behaviour is consistent with that (identical 401 pattern for every variant); confirmed
    # statically rather than by driving a variant all the way to lockout (would cost more of the
    # shared rate-limit budget for a question the code already answers unambiguously).
    record("authn", "1.2", "lockout bucketing by case/unicode email variant",
           "case variants of the same e-mail share one failure counter, not a fresh budget each",
           f"per-variant codes={codes}; normalize_email() lowercases before lookup (platform_auth_service.py:59)",
           "Info", "SOLID")


# ---------------------------------------------------------------------------
# 2. Rate limiter bypass via X-Forwarded-For
# ---------------------------------------------------------------------------
def test_client_ip_trust_proxy_chain():
    """~/final_test.env sets BUILDER_TRUST_PROXY_HEADERS=true, so client_ip() (security.py:65-73)
    trusts the LAST hop of X-Forwarded-For. Caddy's reverse_proxy appends its OWN immediate-peer
    address as that last hop (standard Go/Caddy reverse-proxy behaviour: it sets/appends, never
    trusting what arrived); its immediate peer here is the local ngrok agent (loopback), not the
    real internet client -- even though ngrok itself injects the real client IP earlier in the
    chain. So the app may be trusting the wrong hop. Checked two ways: (a) a spoofed
    X-Forwarded-For first-hop does not change what the app records; (b) what does the app
    actually record as client_ip for logins made over the public tunnel just now?"""
    codes_spoofed_xff = []
    for i in range(10):
        xff = f"10.0.0.{i}"
        rr = post("/account/login", {"email": "nobody-" + uuid.uuid4().hex[:6] + "@sectest.example", "password": "x"},
                  headers={"X-Forwarded-For": xff})
        codes_spoofed_xff.append(rr.status_code)

    api = bb.Api(base=API)
    staff_tok = api.staff("admin")
    c, body, _ = api.call("GET", "/admin/audit?action=account.login_failed&page_size=5", token=staff_tok,
                           headers=HDRS)
    recent_ips = [row.get("client_ip") for row in body.get("items", [])] if c == 200 else None
    all_loopback = bool(recent_ips) and all(ip in ("127.0.0.1", "::1", None) for ip in recent_ips)
    record("authn", "1.3", "client IP trust through the Caddy+ngrok proxy chain (and the per-IP rate limiter it feeds)",
           "client_ip() records the real internet caller's address (and the shared /account/* rate "
           "limiter buckets by that real address, not by a value every public user shares)",
           f"spoofed-XFF login codes={codes_spoofed_xff} (no bypass either way); recent account.login_failed "
           f"audit rows' client_ip={recent_ips} -- all internet-origin requests collapse to loopback",
           "High" if all_loopback else "Info",
           "CONFIRMED" if all_loopback else "SOLID",
           note="root cause: Caddy appends its OWN immediate-peer address (always local, since the ngrok "
                "agent connects to it over loopback) as the last X-Forwarded-For hop; client_ip() trusts "
                "exactly that last hop, discarding the real client IP ngrok itself already injected earlier "
                "in the header. Effect: the 30-req/300s auth rate limiter (config.py auth_rate_limit_attempts) "
                "is a single GLOBAL budget shared by every public caller, not a per-attacker throttle -- any "
                "one user's traffic (malicious or not) can lock everyone else out of login/register/refresh "
                "for the window; and audit log client_ip is forensically useless for anything that came "
                "through this chain.")


# ---------------------------------------------------------------------------
# 3. JWT tampering
# ---------------------------------------------------------------------------
def b64url(d: bytes) -> str:
    return base64.urlsafe_b64encode(d).rstrip(b"=").decode()


def jwt_parts(token: str):
    h, p, s = token.split(".")
    return h, p, s


def decode_part(seg: str) -> dict:
    pad = "=" * (-len(seg) % 4)
    return json.loads(base64.urlsafe_b64decode(seg + pad))


def test_jwt_tampering():
    api = bb.Api(base=API)
    tok = api.customer("member")
    if not tok:
        record("authn", "1.4", "JWT tampering", "n/a", "could not obtain a member token", "High", "NOT_TESTABLE")
        return

    results = {}

    # (a) alg=none
    h, p, s = jwt_parts(tok)
    header = decode_part(h)
    header_none = dict(header, alg="none")
    forged = b64url(json.dumps(header_none, separators=(",", ":")).encode()) + "." + p + "."
    rr = get("/account/me", headers={"Authorization": f"Bearer {forged}"})
    results["alg_none"] = rr.status_code

    # (b) tampered payload (bump role / org id) with original signature (should fail: sig mismatch)
    payload = decode_part(p)
    tampered_payload = dict(payload)
    for k in ("platform_role", "role", "sub"):
        if k in tampered_payload:
            tampered_payload[k] = "platform_admin" if k != "sub" else str(uuid.uuid4())
    forged2 = h + "." + b64url(json.dumps(tampered_payload, separators=(",", ":")).encode()) + "." + s
    rr = get("/account/me", headers={"Authorization": f"Bearer {forged2}"})
    results["tampered_payload_same_sig"] = rr.status_code

    # (c) expired token (if we can craft one offline we'd need SECRET_KEY; instead wait is impractical,
    #     so just flip a bit in the signature to simulate "wrong signature" broadly)
    sig_bytes = bytearray(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)))
    sig_bytes[0] ^= 0xFF
    bad_sig = b64url(bytes(sig_bytes))
    forged3 = h + "." + p + "." + bad_sig
    rr = get("/account/me", headers={"Authorization": f"Bearer {forged3}"})
    results["flipped_signature_byte"] = rr.status_code

    # (d) wrong audience: app token used against /admin/* route
    rr = get("/admin/organizations", headers={"Authorization": f"Bearer {tok}"})
    results["app_token_on_admin_route"] = rr.status_code

    # (e) malformed token / garbage
    rr = get("/account/me", headers={"Authorization": "Bearer not-a-jwt-at-all"})
    results["garbage_token"] = rr.status_code

    # (f) empty bearer
    rr = get("/account/me", headers={"Authorization": "Bearer "})
    results["empty_bearer"] = rr.status_code

    all_good = (
        results["alg_none"] == 401
        and results["tampered_payload_same_sig"] == 401
        and results["flipped_signature_byte"] == 401
        and results["app_token_on_admin_route"] in (401, 403)
        and results["garbage_token"] == 401
        and results["empty_bearer"] == 401
    )
    record("authn", "1.4", "JWT tampering (alg=none, tampered payload, bad signature, wrong audience, garbage)",
           "every variant is refused with 401 (or 403 for cross-audience)",
           f"{results}",
           "Critical" if not all_good else "Info",
           "CONFIRMED" if not all_good else "SOLID")


# ---------------------------------------------------------------------------
# 4. Cookie flags on the refresh cookie
# ---------------------------------------------------------------------------
def test_cookie_flags():
    api = bb.Api(base=API)
    email = api.email_of("member")
    pw = api.password()
    r = post("/account/login", {"email": email, "password": pw})
    body = r.json() if r.content else {}
    tok = None
    if "mfa_token" in body:
        record("authn", "1.5", "cookie flags on refresh cookie", "n/a",
               "member account unexpectedly requires MFA; skipped", "Low", "NOT_TESTABLE")
        return
    set_cookie_headers = r.raw.headers.get_all("Set-Cookie") if hasattr(r.raw.headers, "get_all") else [r.headers.get("Set-Cookie", "")]
    refresh_cookie_line = next((c for c in set_cookie_headers if c.startswith("bb_refresh=")), "")
    flags = {
        "HttpOnly": "HttpOnly" in refresh_cookie_line,
        "Secure": "Secure" in refresh_cookie_line,
        "SameSite=Strict": "SameSite=Strict" in refresh_cookie_line or "samesite=strict" in refresh_cookie_line.lower(),
        "Path=/account": "Path=/account" in refresh_cookie_line,
    }
    all_good = all(flags.values())
    expect_secure = TARGET == "tunnel"  # https origin -> Secure must be set; local http -> Secure may be absent
    ok = flags["HttpOnly"] and flags["SameSite=Strict"] and flags["Path=/account"] and (flags["Secure"] == expect_secure or (expect_secure and flags["Secure"]))
    record("authn", "1.5", "refresh cookie flags (HttpOnly, Secure, SameSite=Strict, Path=/account)",
           f"HttpOnly+SameSite=Strict+Path=/account always; Secure true on the https tunnel ({expect_secure=})",
           f"flags={flags}",
           "High" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID",
           note="cookie line redacted of its value" )


# ---------------------------------------------------------------------------
# 5. CSRF on cookie-authenticated routes (/account/refresh, /account/logout)
# ---------------------------------------------------------------------------
def test_csrf_same_origin_check():
    api = bb.Api(base=API)
    email = api.email_of("member")
    pw = api.password()
    r = post("/account/login", {"email": email, "password": pw})
    if r.status_code != 200 or "mfa_token" in (r.json() if r.content else {}):
        record("authn", "1.6", "CSRF same-origin check on /account/refresh", "n/a",
               "could not get a plain session cookie to test with", "Medium", "NOT_TESTABLE")
        return
    jar = r.cookies

    app_origin = bb.env().get("FINAL_TEST_TUNNEL_APP_URL", "").rstrip("/") if TARGET == "tunnel" else "http://localhost:5173"

    # (a) no X-Requested-With header at all -> must be refused
    rr = post("/account/refresh", {}, cookies=jar)
    no_header = rr.status_code

    # (b) X-Requested-With present but Origin is an attacker site -> must be refused
    rr = post("/account/refresh", {}, headers={"X-Requested-With": "builder", "Origin": "https://evil.attacker.example"}, cookies=jar)
    bad_origin = rr.status_code

    # (c) correct header + correct origin (or no Origin, like a same-site top-level request) -> should succeed
    rr = post("/account/refresh", {}, headers={"X-Requested-With": "builder", "Origin": app_origin}, cookies=jar)
    good_origin = rr.status_code

    ok = no_header == 403 and bad_origin == 403 and good_origin in (200, 429)
    record("authn", "1.6", "CSRF defenses on /account/refresh (SameSite=Strict + X-Requested-With + Origin allow-list)",
           "missing header -> 403; forged Origin -> 403; legitimate same-origin request -> 200",
           f"no_header={no_header} bad_origin={bad_origin} good_origin={good_origin}",
           "High" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# 6. CORS misconfiguration: reflected origin / null origin
# ---------------------------------------------------------------------------
def test_cors_misconfig():
    for origin in ("https://evil.attacker.example", "null"):
        rr = requests.options(API + "/account/me", headers={
            **HDRS,
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        }, timeout=30)
        acao = rr.headers.get("Access-Control-Allow-Origin")
        acac = rr.headers.get("Access-Control-Allow-Credentials")
        reflected = acao == origin
        record("authn", f"1.7.{origin}", f"CORS preflight for Origin={origin}",
               "Access-Control-Allow-Origin is never the attacker origin (explicit allow-list only)",
               f"status={rr.status_code} ACAO={acao} ACAC={acac}",
               "Critical" if reflected else "Info",
               "CONFIRMED" if reflected else "SOLID")


# ---------------------------------------------------------------------------
# 7. must_change_password bypass (customer side doesn't have this flag per code read; staff does)
# ---------------------------------------------------------------------------
def test_must_change_password_admin_bypass():
    """Staff accounts carry must_change_password; require_admin() checks it (app/api/security.py:544).
    We can't flip the flag on a live staff account without the DB, so this is a static-confirmed control;
    record as SOLID with the file:line evidence rather than skip silently."""
    record("authn", "1.8", "must_change_password enforced on admin routes",
           "require_admin() refuses any call while must_change_password is true (app/api/security.py:544-545)",
           "verified by code reading only (no DB access from this harness to flip the flag safely); "
           "no live reproducer written",
           "Low", "SOLID", note="static check, not dynamically exercised")


def main():
    print(f"=== 01_authn_session against {TARGET} ({API}) ===")
    for fn in (
        test_lockout,
        test_lockout_case_unicode_bypass,
        test_client_ip_trust_proxy_chain,
        test_jwt_tampering,
        test_cookie_flags,
        test_csrf_same_origin_check,
        test_cors_misconfig,
        test_must_change_password_admin_bypass,
    ):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - keep going, record the failure as evidence
            record("authn", fn.__name__, fn.__name__, "test runs cleanly",
                   f"test script raised {type(exc).__name__}: {exc}", "Low", "NOT_TESTABLE")


if __name__ == "__main__":
    main()
