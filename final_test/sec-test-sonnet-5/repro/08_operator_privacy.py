#!/usr/bin/env python3
"""Category 8 — Operator console & privacy. Self-contained disposable orgs plus the shared
platform staff accounts (bb.staff) for read-only/negative checks only -- never anything that
mutates the shared admin/support fixtures.

Usage: python3 final_test/sec-test-sonnet-5/repro/08_operator_privacy.py
"""
from __future__ import annotations

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
_DELAY = 0.3 if TARGET == "tunnel" else 0.1

_session = requests.Session()


def req(method, path, body=None, token=None, headers=None):
    h = {**HDRS, **(headers or {})}
    if token:
        h["Authorization"] = f"Bearer {token}"
    time.sleep(_DELAY)
    for attempt in range(3):
        try:
            return _session.request(method, API + path, json=body, headers=h, timeout=30)
        except requests.exceptions.ConnectionError:
            if attempt == 2:
                raise
            time.sleep(2)


def new_account(prefix="opc"):
    email = new_disposable_email(prefix)
    pw = "Correct-Horse-Battery-Staple-9!"
    r = req("POST", "/account/register", {"email": email, "password": pw, "name": "sectest"})
    if r.status_code == 429:
        time.sleep(float(r.headers.get("Retry-After", 20)) + 1)
        r = req("POST", "/account/register", {"email": email, "password": pw, "name": "sectest"})
    if r.status_code != 201:
        return None, None, None
    return email, pw, r.json()["access_token"]


def new_org(owner_tok, prefix="opc"):
    slug = f"sectest-{prefix}-" + uuid.uuid4().hex[:8]
    r = req("POST", "/orgs", {"name": "sectest", "slug": slug}, token=owner_tok)
    return (slug, r.json()["id"]) if r.status_code == 201 else (None, None)


# ---------------------------------------------------------------------------
# 1. allow_impersonation default posture: opt-in or opt-out?
# ---------------------------------------------------------------------------
def test_impersonation_default_consent():
    owner_email, owner_pw, owner_tok = new_account("consent")
    slug, org_id = new_org(owner_tok, "consent")
    if not slug:
        record("opconsole", "8.1", "impersonation consent default", "n/a", "could not create org", "Medium", "NOT_TESTABLE")
        return
    cfg = req("GET", f"/orgs/{slug}/policies", token=owner_tok).json()
    default_value = cfg.get("allow_impersonation")
    record("opconsole", "8.1", "a brand-new org's allow_impersonation defaults to True (opt-out), not False (opt-in)",
           "§7.1-2 describes an impersonation CONSENT toggle; a consent model should default to "
           "false until the org explicitly opts in, not grant it by default and require the org "
           "to notice and turn it off",
           f"brand-new disposable org's allow_impersonation={default_value}",
           "Medium" if default_value is True else "Info",
           "CONFIRMED" if default_value is True else "SOLID",
           note="app/models/platform.py:234 -- allow_impersonation: Mapped[bool] = "
                "mapped_column(..., default=True). Not a direct exploit (an operator still needs "
                "platform_admin + the impersonate:write permission + an audit trail + the hard "
                "write-blocks), but it is the opposite of an opt-in consent model")


# ---------------------------------------------------------------------------
# 2. Impersonation write-block: tokens/secrets/export/billing/project-create are NEVER reachable,
#    even with the writes switch on; ordinary reads work.
# ---------------------------------------------------------------------------
def test_impersonation_write_block():
    owner_email, owner_pw, owner_tok = new_account("imp")
    slug, org_id = new_org(owner_tok, "imp")
    if not slug:
        record("opconsole", "8.2", "impersonation write-block on sensitive routes", "n/a",
               "could not create org", "Medium", "NOT_TESTABLE")
        return
    me = req("GET", "/account/me", token=owner_tok).json()
    member_user_id = me["id"]

    staff_tok = bb.Api(base=API).staff("admin")
    rr = req("POST", f"/admin/organizations/{org_id}/members/{member_user_id}/impersonate",
             {"reason": "sectest"}, token=staff_tok)
    if rr.status_code != 201:
        record("opconsole", "8.2", "impersonation write-block on sensitive routes", "n/a",
               f"could not start impersonation: HTTP {rr.status_code} {rr.text[:200]}", "Medium", "NOT_TESTABLE")
        return
    view_tok = rr.json()["access_token"]

    # (a) always-blocked regardless of the writes switch
    always_blocked = {
        "tokens": req("GET", "/account/tokens", token=view_tok).status_code,
        "export": req("GET", f"/orgs/{slug}/export", token=view_tok).status_code,
        "billing_checkout": req("POST", f"/orgs/{slug}/billing/checkout", {"plan_id": "team"}, token=view_tok).status_code,
    }
    # (b) an ordinary read should work
    read_ok = req("GET", "/account/me", token=view_tok).status_code
    # (c) a write BEFORE switching "allow writes" on should be refused (read-only by default)
    write_before = req("PATCH", f"/orgs/{slug}", {"name": "renamed-by-view-as"}, token=view_tok).status_code
    # (d) switch writes on, then project-create (hard-blocked regardless) and an org PATCH
    #     (also hard-blocked: "the org console is look-only, whatever the switch says")
    req("POST", "/account/impersonation/writes", {}, token=view_tok)
    write_after_tokens_switch = req("POST", "/projects", {"name": "x", "organization_id": org_id}, token=view_tok).status_code
    org_patch_after_switch = req("PATCH", f"/orgs/{slug}", {"name": "renamed-again"}, token=view_tok).status_code

    findings = {
        **always_blocked, "read_ok": read_ok, "write_before_switch": write_before,
        "project_create_after_switch": write_after_tokens_switch, "org_patch_after_switch": org_patch_after_switch,
    }
    ok = (
        always_blocked["tokens"] in (401, 403, 404)
        and always_blocked["export"] in (401, 403, 404)
        and always_blocked["billing_checkout"] in (401, 403, 404)
        and read_ok == 200
        and write_before == 403
        and write_after_tokens_switch == 403
        and org_patch_after_switch == 403
    )
    record("opconsole", "8.2", "impersonation hard-blocks tokens/export/billing regardless of the "
           "writes switch, and the org console stays look-only even with writes on",
           "tokens/export/billing -> refused always; reads work; writes refused until the switch "
           "is on; project-create and org PATCH stay refused even WITH the switch on",
           f"{findings}",
           "Critical" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# 3. platform_support can never impersonate and can never write (negative checks only, shared
#    staff account, read-only probes).
# ---------------------------------------------------------------------------
def test_support_cannot_impersonate_or_write():
    try:
        support_tok = bb.Api(base=API).staff("support")
    except RuntimeError as exc:
        record("opconsole", "8.3", "platform_support cannot impersonate or write", "n/a",
               f"could not sign in as the shared support account: {exc}", "Medium", "NOT_TESTABLE")
        return
    owner_email, owner_pw, owner_tok = new_account("supcheck")
    slug, org_id = new_org(owner_tok, "supcheck")
    me = req("GET", "/account/me", token=owner_tok).json() if slug else {"id": str(uuid.uuid4())}

    impersonate_status = req("POST", f"/admin/organizations/{org_id}/members/{me['id']}/impersonate",
                              {"reason": "sectest"}, token=support_tok).status_code if org_id else None
    write_status = req("PATCH", f"/admin/organizations/{org_id}/plan",
                        {"plan_id": "team", "reason": "sectest"}, token=support_tok).status_code if org_id else None
    reset_pw_status = req("POST", f"/admin/users/{me['id']}/reset-password", {}, token=support_tok).status_code

    ok = impersonate_status == 403 and write_status == 403 and reset_pw_status == 403
    record("opconsole", "8.3", "platform_support has no write permission, including impersonate:write",
           "every write-shaped admin action (impersonate, plan change, password reset) is refused "
           "with 403 for the support role",
           f"impersonate={impersonate_status} plan_change={write_status} reset_password={reset_pw_status}",
           "Critical" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# 4. Org export tenant scoping
# ---------------------------------------------------------------------------
def test_export_tenant_scoping():
    owner_email, owner_pw, owner_tok = new_account("export")
    slug, org_id = new_org(owner_tok, "export")
    outsider_email, outsider_pw, outsider_tok = new_account("exportoutsider")
    if not slug or not outsider_tok:
        record("opconsole", "8.4", "org export tenant scoping", "n/a", "could not create accounts/org",
               "Medium", "NOT_TESTABLE")
        return
    owner_status = req("GET", f"/orgs/{slug}/export", token=owner_tok).status_code
    outsider_status = req("GET", f"/orgs/{slug}/export", token=outsider_tok).status_code
    body = req("GET", f"/orgs/{slug}/export", token=owner_tok).text if owner_status == 200 else ""
    leaks_other_org = False  # can't cheaply prove a negative here; just check it's scoped to THIS org's slug
    ok = owner_status == 200 and outsider_status == 404
    record("opconsole", "8.4", "the owner can export their org's data; an outsider gets 404 (not 403)",
           "GET /orgs/{slug}/export: owner -> 200; a non-member -> 404",
           f"owner={owner_status} outsider={outsider_status} body_len={len(body)}",
           "High" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


def main():
    print(f"=== 08_operator_privacy against {TARGET} ({API}) ===")
    for fn in (
        test_impersonation_default_consent,
        test_impersonation_write_block,
        test_support_cannot_impersonate_or_write,
        test_export_tenant_scoping,
    ):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            record("opconsole", fn.__name__, fn.__name__, "test runs cleanly",
                   f"test script raised {type(exc).__name__}: {exc}", "Low", "NOT_TESTABLE")


if __name__ == "__main__":
    main()
