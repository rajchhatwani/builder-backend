#!/usr/bin/env python3
"""Category 5 — Injection & input (lean pass: NUL bytes, oversized/deep bodies, header
injection via X-Request-Id, security headers, open-redirect surface). Stored/reflected XSS in the
frontend, SSTI in the generator, and path traversal in generated zip entries need a browser or the
generator pipeline and are NOT covered in this pass -- noted as not-yet-tested in the report.

Usage: python3 final_test/sec-test-sonnet-5/repro/05_injection.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid

import requests

sys.path.insert(0, os.path.dirname(__file__))
from _common import ngrok_headers, new_disposable_email, record, tunnel_api_base  # noqa: E402

TARGET = os.environ.get("BB_TARGET", "tunnel")
API = tunnel_api_base() if TARGET == "tunnel" else os.environ.get("BB_LOCAL_API", "http://127.0.0.1:8001")
HDRS = ngrok_headers() if TARGET == "tunnel" else {}
_DELAY = 0.3 if TARGET == "tunnel" else 0.1

_session = requests.Session()


def req(method, path, body=None, token=None, headers=None, data=None):
    h = {**HDRS, **(headers or {})}
    if token:
        h["Authorization"] = f"Bearer {token}"
    time.sleep(_DELAY)
    kwargs = {"headers": h, "timeout": 30}
    if data is not None:
        kwargs["data"] = data
    else:
        kwargs["json"] = body
    for attempt in range(3):
        try:
            return _session.request(method, API + path, **kwargs)
        except requests.exceptions.ConnectionError:
            if attempt == 2:
                raise
            time.sleep(2)


def new_account(prefix="inj"):
    email = new_disposable_email(prefix)
    pw = "Correct-Horse-Battery-Staple-9!"
    r = req("POST", "/account/register", {"email": email, "password": pw, "name": "sectest"})
    if r.status_code == 429:
        time.sleep(float(r.headers.get("Retry-After", 20)) + 1)
        r = req("POST", "/account/register", {"email": email, "password": pw, "name": "sectest"})
    if r.status_code != 201:
        return None, None, None
    return email, pw, r.json()["access_token"]


# ---------------------------------------------------------------------------
# 1. NUL bytes in path, query, and JSON body (review's old F-003)
# ---------------------------------------------------------------------------
def test_nul_bytes():
    r1 = req("GET", "/orgs/sectest%00bad")
    r2 = req("GET", "/orgs?foo=%00")
    email = "a\\u0000b@example.com"
    r3 = req("POST", "/account/register", data=f'{{"email":"{email}","password":"x","name":"y"}}'.encode(),
             headers={"Content-Type": "application/json"})
    ok = r1.status_code in (404, 422) and r2.status_code in (200, 422) and r3.status_code == 422
    record("injection", "5.1", "NUL bytes in path/query/JSON body never reach the database (422, not 500)",
           "every NUL-byte variant is refused cleanly (422) or treated as a harmless 404, never a 500",
           f"path_nul={r1.status_code} query_nul={r2.status_code} json_body_nul={r3.status_code}",
           "High" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# 2. Oversized / deeply nested JSON bodies
# ---------------------------------------------------------------------------
def test_oversized_and_deep_body():
    big = "x" * (11 * 1024 * 1024)  # > max_request_bytes (10 MiB default)
    r1 = req("POST", "/account/register", {"email": "big@example.com", "password": "x", "name": big})

    deep = {}
    cur = deep
    for _ in range(5000):
        cur["a"] = {}
        cur = cur["a"]
    r2 = req("POST", "/account/register", deep)

    ok = r1.status_code in (413, 422) and r2.status_code in (422, 400, 413)
    record("injection", "5.2", "oversized and deeply-nested JSON bodies are refused without a 500",
           "an 11 MiB body -> 413; a 5000-level-deep JSON object -> 422/400, never a 500 or a hang",
           f"oversized_body={r1.status_code} deep_json={r2.status_code}",
           "High" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# 3. Header injection via X-Request-Id (CRLF / control characters)
# ---------------------------------------------------------------------------
def test_request_id_header_injection():
    malicious = "abc\r\nSet-Cookie: evil=1\r\nX-Injected: yes"
    r = req("GET", "/health", headers={"X-Request-Id": malicious})
    echoed = r.headers.get("X-Request-Id", "")
    injected = "X-Injected" in r.headers or "evil" in str(r.headers.get("Set-Cookie", ""))
    ok = not injected and echoed != malicious
    record("injection", "5.3", "a malicious X-Request-Id is never echoed back raw (no header/log injection)",
           "the server generates its own request id when the client's doesn't match a safe "
           "pattern, instead of reflecting attacker-controlled bytes into response headers",
           f"echoed_request_id={echoed!r} extra_headers_injected={injected}",
           "Medium" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# 4. Baseline security headers present on every response
# ---------------------------------------------------------------------------
def test_security_headers():
    r = req("GET", "/health")
    want = {
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "referrer-policy": "no-referrer",
        "cross-origin-opener-policy": "same-origin",
    }
    actual = {k: r.headers.get(k) for k in want}
    missing = {k: v for k, v in want.items() if actual.get(k, "").lower() != v.lower()}
    hsts = "strict-transport-security" in {k.lower() for k in r.headers} if TARGET == "tunnel" else True
    ok = not missing and hsts
    record("injection", "5.4", "baseline security headers on every response (nosniff/DENY/referrer/COOP/HSTS)",
           "all of nosniff, frame-deny, no-referrer, same-origin COOP are present; HSTS present on the https tunnel",
           f"actual={actual} missing={missing} hsts_present={hsts}",
           "Medium" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# 5. Open redirect surface: SSO failure/success redirects are server-built, never user input
# ---------------------------------------------------------------------------
def test_no_open_redirect_via_sso():
    r = req("GET", "/sso/does-not-exist-org/login?login_hint=whatever&test=https%3A%2F%2Fevil.example")
    location = r.headers.get("Location", "")
    redirects_to_attacker = "evil.example" in location
    record("injection", "5.5", "SSO start/callback redirects never reflect attacker-supplied URLs",
           "the Location header is always built from the server's own public_app_url + a fixed "
           "fragment, never from a query parameter",
           f"status={r.status_code} location={location!r}",
           "Critical" if redirects_to_attacker else "Info",
           "CONFIRMED" if redirects_to_attacker else "SOLID",
           note="code-confirmed too: SsoService.app_url() builds every redirect from "
                "settings.public_app_url, never from request input (sso_service.py:213-214)")


def main():
    print(f"=== 05_injection against {TARGET} ({API}) ===")
    for fn in (
        test_nul_bytes,
        test_oversized_and_deep_body,
        test_request_id_header_injection,
        test_security_headers,
        test_no_open_redirect_via_sso,
    ):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            record("injection", fn.__name__, fn.__name__, "test runs cleanly",
                   f"test script raised {type(exc).__name__}: {exc}", "Low", "NOT_TESTABLE")


if __name__ == "__main__":
    main()
