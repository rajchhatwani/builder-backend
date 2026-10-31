#!/usr/bin/env python3
"""Category 4 — API tokens / PATs. Self-contained disposable accounts/orgs. Tunnel by default.

Usage: python3 final_test/sec-test-sonnet-5/repro/04_api_tokens.py
"""
from __future__ import annotations

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


def req(method, path, body=None, token=None, headers=None):
    h = {**HDRS, **(headers or {})}
    if token:
        h["Authorization"] = f"Bearer {token}"
    time.sleep(_DELAY)
    return _session.request(method, API + path, json=body, headers=h, timeout=30)


def new_account(prefix="tok"):
    email = new_disposable_email(prefix)
    pw = "Correct-Horse-Battery-Staple-9!"
    r = req("POST", "/account/register", {"email": email, "password": pw, "name": "sectest"})
    if r.status_code == 429:
        time.sleep(float(r.headers.get("Retry-After", 15)) + 1)
        r = req("POST", "/account/register", {"email": email, "password": pw, "name": "sectest"})
    if r.status_code != 201:
        return None, None, None
    return email, pw, r.json()["access_token"]


def new_org(owner_tok, prefix="tok"):
    slug = f"sectest-{prefix}-" + uuid.uuid4().hex[:8]
    r = req("POST", "/orgs", {"name": "sectest", "slug": slug}, token=owner_tok)
    return slug if r.status_code == 201 else None


def mint_token(session_tok, scopes, project_id=None, name="sectest-token"):
    body = {"name": name, "scopes": scopes, "expires_in_days": 7}
    if project_id:
        body["project_id"] = project_id
    r = req("POST", "/account/tokens", body, token=session_tok)
    if r.status_code != 201:
        return None, r
    return r.json()["token"], r


# ---------------------------------------------------------------------------
# 1. Scope enforcement: read-only token on write routes; write token on session-only routes
# ---------------------------------------------------------------------------
def test_scope_enforcement():
    owner_email, owner_pw, owner_tok = new_account("scope")
    slug = new_org(owner_tok, "scope")
    if not slug:
        record("pat", "4.1", "scope enforcement", "n/a", "could not create disposable org", "Medium", "NOT_TESTABLE")
        return

    read_tok, _ = mint_token(owner_tok, ["read"])
    write_tok, _ = mint_token(owner_tok, ["write"])
    if not read_tok or not write_tok:
        record("pat", "4.1", "scope enforcement", "n/a", "could not mint read/write tokens", "Medium", "NOT_TESTABLE")
        return

    # (a) read-only token tries a write route
    r1 = req("PATCH", f"/orgs/{slug}", {"name": "renamed"}, token=read_tok)
    read_on_write = r1.status_code

    # (b) write-scope token tries a SESSION-ONLY route (ORG_ROUTES_SESSION_ONLY: delete, member
    #     role/remove, transfer, billing checkout/portal, export)
    r2 = req("DELETE", f"/orgs/{slug}", token=write_tok)
    write_on_delete = r2.status_code
    r3 = req("POST", f"/orgs/{slug}/billing/checkout", {"plan_id": "team"}, token=write_tok)
    write_on_checkout = r3.status_code

    ok = read_on_write == 403 and write_on_delete == 403 and write_on_checkout == 403
    record("pat", "4.1", "API token scope enforcement (read vs write) and session-only gate",
           "a read-only token cannot write (403); a write-scope token still cannot delete the org "
           "or open billing checkout (403 session_required) -- those need a real session",
           f"read_token_on_PATCH={read_on_write} write_token_on_DELETE={write_on_delete} "
           f"write_token_on_checkout={write_on_checkout}",
           "Critical" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# 2. Destructive org actions by a write-scope token (direct repro of the review's old F-002)
# ---------------------------------------------------------------------------
def test_destructive_actions_by_token():
    owner_email, owner_pw, owner_tok = new_account("destruct")
    slug = new_org(owner_tok, "destruct")
    if not slug:
        record("pat", "4.2", "destructive org actions via API token", "n/a", "could not create org", "Medium", "NOT_TESTABLE")
        return
    write_tok, _ = mint_token(owner_tok, ["read", "write"])
    if not write_tok:
        record("pat", "4.2", "destructive org actions via API token", "n/a", "could not mint token", "Medium", "NOT_TESTABLE")
        return

    me = req("GET", "/account/me", token=owner_tok).json()
    probes = [
        ("DELETE", f"/orgs/{slug}", None),
        ("POST", f"/orgs/{slug}/transfer", {"new_owner_id": me["id"]}),
        ("PATCH", f"/orgs/{slug}/members/{me['id']}", {"role": "admin"}),
        ("DELETE", f"/orgs/{slug}/members/{me['id']}", None),
        ("POST", f"/orgs/{slug}/billing/checkout", {"plan_id": "team"}),
        ("POST", f"/orgs/{slug}/billing/portal", None),
        ("GET", f"/orgs/{slug}/export", None),
    ]
    bad = []
    for method, path, body in probes:
        r = req(method, path, body, token=write_tok)
        if r.status_code != 403:
            bad.append((method, path, r.status_code))
    ok = len(bad) == 0
    record("pat", "4.2", "a write-scope API token cannot do owner-level/destructive org actions",
           "delete/transfer/role-change/remove-member/checkout/portal/export are all session-only "
           "(403 session_required) for an API token, even with write scope",
           f"failures={bad}" if bad else f"all {len(probes)} probes correctly refused",
           "Critical" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# 3. Token minting tokens: can an API token mint/revoke other tokens?
# ---------------------------------------------------------------------------
def test_token_cannot_mint_tokens():
    owner_email, owner_pw, owner_tok = new_account("mint")
    write_tok, _ = mint_token(owner_tok, ["read", "write"])
    if not write_tok:
        record("pat", "4.3", "token cannot mint/list/revoke tokens", "n/a", "could not mint token", "Medium", "NOT_TESTABLE")
        return

    r1 = req("POST", "/account/tokens", {"name": "child", "scopes": ["read"], "expires_in_days": 1}, token=write_tok)
    r2 = req("GET", "/account/tokens", token=write_tok)
    ok = r1.status_code in (401, 403) and r2.status_code in (401, 403)
    record("pat", "4.3", "an API token cannot mint or list API tokens (session_principal only)",
           "both POST and GET /account/tokens require a real session and refuse an API token",
           f"mint_with_token={r1.status_code} list_with_token={r2.status_code}",
           "High" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# 4. Pinned-token escape: a project-pinned token tries org-level routes and another project
# ---------------------------------------------------------------------------
def test_pinned_token_escape():
    owner_email, owner_pw, owner_tok = new_account("pin")
    slug = new_org(owner_tok, "pin")
    if not slug:
        record("pat", "4.4", "pinned-token escape", "n/a", "could not create org", "Medium", "NOT_TESTABLE")
        return
    org = req("GET", f"/orgs/{slug}", token=owner_tok).json()
    # project slugs are globally unique across the WHOLE platform (see authz/3.7), so a plain
    # "p1"/"p2" can collide with an unrelated project from a previous run; use unique names.
    n1, n2 = f"sectest-pin-{uuid.uuid4().hex[:8]}", f"sectest-pin-{uuid.uuid4().hex[:8]}"
    p1 = req("POST", "/projects", {"name": n1, "organization_id": org["id"]}, token=owner_tok)
    p2 = req("POST", "/projects", {"name": n2, "organization_id": org["id"]}, token=owner_tok)
    if p1.status_code != 201 or p2.status_code != 201:
        record("pat", "4.4", "pinned-token escape", "n/a", "could not create two projects", "Medium", "NOT_TESTABLE")
        return
    proj1_id, proj2_id = p1.json()["id"], p2.json()["id"]

    pinned_tok, resp = mint_token(owner_tok, ["read", "write"], project_id=proj1_id)
    if not pinned_tok:
        record("pat", "4.4", "pinned-token escape", "n/a", f"could not mint pinned token: {resp.status_code}", "Medium", "NOT_TESTABLE")
        return

    # (a) pinned token tries an ORG-level route -> must be refused (org_context refuses any
    #     token_project_id != None)
    r1 = req("GET", f"/orgs/{slug}", token=pinned_tok)
    # (b) pinned token tries its OWN project -> should work
    r2 = req("GET", f"/projects/{proj1_id}", token=pinned_tok)
    # (c) pinned token tries the OTHER project in the SAME org -> must be refused
    r3 = req("GET", f"/projects/{proj2_id}", token=pinned_tok)

    ok = r1.status_code == 403 and r2.status_code == 200 and r3.status_code in (403, 404)
    record("pat", "4.4", "a project-pinned API token cannot reach org routes or a different project",
           "org-level route -> 403; its own project -> 200; a sibling project in the same org -> 403/404",
           f"org_route={r1.status_code} own_project={r2.status_code} other_project={r3.status_code}",
           "Critical" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# 5. Revoked token is immediately refused
# ---------------------------------------------------------------------------
def test_revoked_token_refused():
    owner_email, owner_pw, owner_tok = new_account("revoke")
    write_tok, resp = mint_token(owner_tok, ["read"])
    if not write_tok:
        record("pat", "4.5", "revoked token refused", "n/a", "could not mint token", "Medium", "NOT_TESTABLE")
        return
    token_id = resp.json()["id"]

    before = req("GET", "/account/me", token=write_tok).status_code
    r = req("DELETE", f"/account/tokens/{token_id}", token=owner_tok)
    revoke_status = r.status_code
    after = req("GET", "/account/me", token=write_tok).status_code

    ok = before == 200 and revoke_status == 204 and after == 401
    record("pat", "4.5", "a revoked API token stops working immediately",
           "token works before revoke (200), revoke succeeds (204), token is refused after (401)",
           f"before={before} revoke={revoke_status} after={after}",
           "High" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


def main():
    print(f"=== 04_api_tokens against {TARGET} ({API}) ===")
    for fn in (
        test_scope_enforcement,
        test_destructive_actions_by_token,
        test_token_cannot_mint_tokens,
        test_pinned_token_escape,
        test_revoked_token_refused,
    ):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            record("pat", fn.__name__, fn.__name__, "test runs cleanly",
                   f"test script raised {type(exc).__name__}: {exc}", "Low", "NOT_TESTABLE")


if __name__ == "__main__":
    main()
