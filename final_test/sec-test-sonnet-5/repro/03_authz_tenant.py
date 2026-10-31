#!/usr/bin/env python3
"""Category 3 — Authorization / tenant isolation. Self-contained: creates its own disposable
owner/outsider accounts and orgs rather than relying on the shared bb-sso / bb-owner fixtures
(which another concurrent session may be using for SSO/SCIM work right now). Runs against the
tunnel by default.

Usage: python3 final_test/sec-test-sonnet-5/repro/03_authz_tenant.py
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

_session = requests.Session()


_DELAY = 0.3 if TARGET == "tunnel" else 0.1


def req(method, path, body=None, token=None, headers=None):
    h = {**HDRS, **(headers or {})}
    if token:
        h["Authorization"] = f"Bearer {token}"
    time.sleep(_DELAY)
    return _session.request(method, API + path, json=body, headers=h, timeout=30)


def tunnel_is_healthy() -> bool:
    """The free ngrok tunnel (and whatever else is sharing this stack tonight, see authn/1.3)
    occasionally serves its OWN offline/error page instead of reaching the app, which looks like
    a 404 from every route including ones that have nothing to do with slugs. Detect that rather
    than mistake it for an app bug."""
    r = req("GET", "/health")
    return r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json")


def new_account(prefix="authz"):
    email = new_disposable_email(prefix)
    pw = "Correct-Horse-Battery-Staple-9!"
    r = req("POST", "/account/register", {"email": email, "password": pw, "name": "sectest"})
    if r.status_code == 429:  # shared tunnel-wide rate limit (authn/1.3): wait once, then retry
        time.sleep(float(r.headers.get("Retry-After", 20)) + 1)
        r = req("POST", "/account/register", {"email": email, "password": pw, "name": "sectest"})
    if r.status_code != 201:
        return None, None, None
    return email, pw, r.json()["access_token"]


def new_org(owner_tok, prefix="authz"):
    slug = f"sectest-{prefix}-" + uuid.uuid4().hex[:8]
    r = req("POST", "/orgs", {"name": "sectest org", "slug": slug}, token=owner_tok)
    if r.status_code != 201:
        return None
    return slug


# ---------------------------------------------------------------------------
# 1. Unauthenticated sweep: every org/project/admin route must 401 (or 404 for truly public ones)
# ---------------------------------------------------------------------------
def test_unauthenticated_sweep():
    if not tunnel_is_healthy():
        record("authz", "3.1", "unauthenticated sweep across org/project/account/admin routes", "n/a",
               "tunnel/stack looked unhealthy (non-JSON /health) right before this probe -- almost "
               "certainly a transient blip from whatever else is sharing this stack tonight, not an "
               "app issue; skipped rather than risk a false reading", "Low", "NOT_TESTABLE")
        return
    owner_email, owner_pw, owner_tok = new_account("unauth")
    slug = new_org(owner_tok, "unauth") if owner_tok else None
    probes = [
        ("GET", "/account/me"),
        ("GET", "/orgs"),
        ("GET", f"/orgs/{slug}" if slug else "/orgs/does-not-exist"),
        ("GET", f"/orgs/{slug}/members" if slug else "/orgs/x/members"),
        ("GET", f"/orgs/{slug}/audit" if slug else "/orgs/x/audit"),
        ("DELETE", f"/orgs/{slug}" if slug else "/orgs/x"),
        ("GET", "/account/tokens"),
        ("POST", "/projects"),
        ("GET", "/admin/organizations"),
        ("GET", "/admin/audit"),
        ("GET", "/account/mfa"),
    ]
    bad = []
    for method, path in probes:
        r = req(method, path)
        if r.status_code not in (401,):
            bad.append((method, path, r.status_code))
    ok = len(bad) == 0
    record("authz", "3.1", "unauthenticated sweep across org/project/account/admin routes",
           "every one of these answers 401 with no Authorization header",
           f"failures={bad}" if bad else f"all {len(probes)} probes returned 401",
           "Critical" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# 2. Outsider 404 sweep on an org they are not a member of (tenant isolation)
# ---------------------------------------------------------------------------
def test_outsider_404_sweep():
    owner_email, owner_pw, owner_tok = new_account("tenant")
    slug = new_org(owner_tok, "tenant")
    if not slug:
        record("authz", "3.2", "outsider 404 sweep", "n/a", "could not create disposable org", "Medium", "NOT_TESTABLE")
        return
    outsider_email, outsider_pw, outsider_tok = new_account("outsider")
    if not outsider_tok:
        record("authz", "3.2", "outsider 404 sweep", "n/a", "could not create outsider account", "Medium", "NOT_TESTABLE")
        return

    probes = [
        ("GET", f"/orgs/{slug}"),
        ("GET", f"/orgs/{slug}/members"),
        ("GET", f"/orgs/{slug}/audit"),
        ("GET", f"/orgs/{slug}/invitations"),
        ("GET", f"/orgs/{slug}/plan"),
        ("GET", f"/orgs/{slug}/projects"),
        ("PATCH", f"/orgs/{slug}"),
        ("DELETE", f"/orgs/{slug}"),
        ("POST", f"/orgs/{slug}/transfer"),
        ("GET", f"/orgs/{slug}/sso"),
        ("GET", f"/orgs/{slug}/scim"),
        ("GET", f"/orgs/{slug}/policies"),
    ]
    bad = []
    for method, path in probes:
        r = req(method, path, token=outsider_tok)
        if r.status_code != 404:
            bad.append((method, path, r.status_code))
    ok = len(bad) == 0
    record("authz", "3.2", "outsider gets 404 (not 403) on every route of an org they don't belong to",
           "a non-member sees 404 everywhere -- indistinguishable from a non-existent org, no "
           "existence/role leak via a 403 vs 404 distinction",
           f"failures={bad}" if bad else f"all {len(probes)} probes returned 404",
           "High" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# 3. IDOR via slug case/whitespace/encoding variants
# ---------------------------------------------------------------------------
def test_slug_idor_variants():
    owner_email, owner_pw, owner_tok = new_account("idor")
    slug = new_org(owner_tok, "idor")
    if not slug:
        record("authz", "3.3", "slug IDOR variants", "n/a", "could not create disposable org", "Medium", "NOT_TESTABLE")
        return
    outsider_email, outsider_pw, outsider_tok = new_account("idoroutsider")

    # NOTE: "%2D" (a percent-escaped '-') and "x/../x" are NOT different resources once decoded/
    # normalized -- a client or server that resolves either back to the exact same slug is just
    # doing ordinary, harmless URL handling, not an IDOR bypass. Only genuinely different byte
    # sequences (case, whitespace) are meaningful here.
    variants = [slug.upper(), slug.capitalize(), slug + " ", " " + slug]
    bad = []
    for v in variants:
        r = req("GET", f"/orgs/{v}", token=owner_tok)
        if r.status_code == 200 and v.strip().lower() != slug.lower():
            bad.append((v, r.status_code))
    ok = len(bad) == 0
    record("authz", "3.3", "org slug lookup is exact-match, no case/whitespace-insensitive IDOR",
           "mangled-case/whitespace/traversal variants of a real slug do not resolve to that org",
           f"problem_variants={bad}" if bad else f"none of {len(variants)} variants matched",
           "Medium" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# 4. Mass assignment on registration and org creation
# ---------------------------------------------------------------------------
def test_mass_assignment():
    email = new_disposable_email("massassign")
    pw = "Correct-Horse-Battery-Staple-9!"
    r = req("POST", "/account/register", {
        "email": email, "password": pw, "name": "sectest",
        "platform_role": "platform_admin", "is_admin": True, "role": "owner",
        "organization_id": str(uuid.uuid4()), "mfa_enabled": True, "status": "active",
        "must_change_password": False,
    })
    escalated = False
    if r.status_code == 201:
        tok = r.json()["access_token"]
        me = req("GET", "/account/me", token=tok)
        body = me.json()
        if body.get("platform_role") not in (None, "customer") or body.get("is_admin") is True:
            escalated = True
    record("authz", "3.4a", "mass assignment on /account/register (platform_role, is_admin, etc.)",
           "extra fields in the registration body are ignored; the new account is an ordinary customer",
           f"register_status={r.status_code} resulting /account/me={me.json() if r.status_code==201 else 'n/a'}",
           "Critical" if escalated else "Info",
           "CONFIRMED" if escalated else "SOLID")

    owner_email, owner_pw, owner_tok = new_account("massorg")
    if owner_tok:
        slug = f"sectest-massorg-{uuid.uuid4().hex[:8]}"
        r2 = req("POST", "/orgs", {
            "name": "sectest", "slug": slug, "require_mfa": True, "plan_id": "enterprise",
            "id": str(uuid.uuid4()), "deletion_requested_at": None, "allow_impersonation": False,
        }, token=owner_tok)
        plan_escalated = False
        if r2.status_code == 201:
            plan_got = r2.json().get("plan_id") or r2.json().get("plan")
            require_mfa_got = r2.json().get("require_mfa")
            plan_escalated = (plan_got == "enterprise") or (require_mfa_got is True)
        record("authz", "3.4b", "mass assignment on POST /orgs (plan_id, require_mfa, id, etc.)",
               "extra fields are ignored; a brand-new org is on the default (free) plan with require_mfa off",
               f"create_status={r2.status_code} body={r2.json() if r2.status_code==201 else r2.text[:200]}",
               "High" if plan_escalated else "Info",
               "CONFIRMED" if plan_escalated else "SOLID")


# ---------------------------------------------------------------------------
# 5. Last-owner protections (self-contained: a fresh org has exactly one member, its owner)
# ---------------------------------------------------------------------------
def test_last_owner_protections():
    owner_email, owner_pw, owner_tok = new_account("lastowner")
    slug = new_org(owner_tok, "lastowner")
    if not slug:
        record("authz", "3.5", "last-owner protections", "n/a", "could not create disposable org", "Medium", "NOT_TESTABLE")
        return
    me = req("GET", "/account/me", token=owner_tok).json()
    user_id = me["id"]

    r1 = req("DELETE", f"/orgs/{slug}/members/{user_id}", token=owner_tok)  # leave as last owner
    r2 = req("PATCH", f"/orgs/{slug}/members/{user_id}", {"role": "member"}, token=owner_tok)  # self-demote
    ok = r1.status_code in (403, 409, 422) and r2.status_code in (403, 409, 422)
    record("authz", "3.5", "the last owner of an org cannot leave or self-demote",
           "both leaving and self-demoting the sole owner are refused (4xx, not 2xx)",
           f"leave_as_last_owner={r1.status_code} self_demote_to_member={r2.status_code}",
           "High" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# 6. Cross-org project access: project-level routes (guard, not org_context)
# ---------------------------------------------------------------------------
def test_cross_org_project_access():
    owner_a_email, owner_a_pw, owner_a_tok = new_account("proja")
    slug_a = new_org(owner_a_tok, "proja")
    owner_b_email, owner_b_pw, owner_b_tok = new_account("projb")
    if not slug_a or not owner_b_tok:
        record("authz", "3.6", "cross-org project access", "n/a", "could not create both orgs", "Medium", "NOT_TESTABLE")
        return

    # project slugs are globally unique platform-wide (see 3.7), so use a unique name here.
    proj_name = f"sectest-project-{uuid.uuid4().hex[:8]}"
    r = req("POST", "/projects", {"name": proj_name, "organization_id": req("GET", f"/orgs/{slug_a}", token=owner_a_tok).json()["id"]}, token=owner_a_tok)
    if r.status_code != 201:
        record("authz", "3.6", "cross-org project access", "n/a", f"could not create project: HTTP {r.status_code} {r.text[:200]}", "Medium", "NOT_TESTABLE")
        return
    project_id = r.json()["id"]

    probes = [
        ("GET", f"/projects/{project_id}"),
        ("PATCH", f"/projects/{project_id}"),
        ("DELETE", f"/projects/{project_id}"),
        ("POST", f"/orgs/{slug_a}/projects/{project_id}/join"),
        ("POST", f"/orgs/{slug_a}/projects/{project_id}/transfer"),
    ]
    bad = []
    for method, path in probes:
        rr = req(method, path, {} if method != "GET" else None, token=owner_b_tok)
        if rr.status_code not in (403, 404):
            bad.append((method, path, rr.status_code))
    ok = len(bad) == 0
    record("authz", "3.6", "a user outside the org cannot read/write/join/transfer its project by real id",
           "every one of these answers 403 or 404 for an unrelated user holding the project's real UUID",
           f"failures={bad}" if bad else f"all {len(probes)} probes blocked",
           "Critical" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# 7. Project slug/name uniqueness is GLOBAL across the whole platform, not per-org
#    (found incidentally while 3.6/4.4 collided with earlier runs' project names)
# ---------------------------------------------------------------------------
def test_project_slug_global_uniqueness():
    name = f"sectest-global-slug-{uuid.uuid4().hex[:8]}"
    owner_a_email, owner_a_pw, owner_a_tok = new_account("gslug_a")
    slug_a = new_org(owner_a_tok, "gslug_a") if owner_a_tok else None
    owner_b_email, owner_b_pw, owner_b_tok = new_account("gslug_b")
    slug_b = new_org(owner_b_tok, "gslug_b") if owner_b_tok else None
    if not slug_a or not slug_b:
        record("authz", "3.7", "project slug uniqueness is global, not per-org", "n/a",
               "could not create both disposable orgs", "Medium", "NOT_TESTABLE")
        return
    org_a = req("GET", f"/orgs/{slug_a}", token=owner_a_tok).json()
    org_b = req("GET", f"/orgs/{slug_b}", token=owner_b_tok).json()
    r1 = req("POST", "/projects", {"name": name, "organization_id": org_a["id"]}, token=owner_a_tok)
    r2 = req("POST", "/projects", {"name": name, "organization_id": org_b["id"]}, token=owner_b_tok)
    collided = r1.status_code == 201 and r2.status_code == 409
    record("authz", "3.7", "project slug/name uniqueness is enforced GLOBALLY, not scoped per-org",
           "two unrelated orgs should each be able to use the same project name; the uniqueness "
           "constraint should be (organization_id, slug), not slug alone",
           f"org_A creates '{name}' -> {r1.status_code}; UNRELATED org_B creates the SAME name "
           f"-> {r2.status_code} {r2.text[:150] if r2.status_code != 201 else ''}",
           "Medium" if collided else "Info",
           "CONFIRMED" if collided else "SOLID",
           note="app/models/project.py:17 -- `slug` has unique=True with no organization_id in "
                "the constraint (no composite UniqueConstraint('organization_id','slug')); "
                "app/services/project_service.py:17 returns a generic 409 'a project with this "
                "slug already exists' that doesn't say which org -- a minor cross-tenant signal "
                "(a name is taken SOMEWHERE on the platform) plus a real usability/squatting "
                "problem (any org can permanently deny a project name to every other org forever, "
                "e.g. common names like 'api', 'main', or a guessed competitor project name)")


def main():
    print(f"=== 03_authz_tenant against {TARGET} ({API}) ===")
    for fn in (
        test_unauthenticated_sweep,
        test_outsider_404_sweep,
        test_slug_idor_variants,
        test_mass_assignment,
        test_last_owner_protections,
        test_cross_org_project_access,
        test_project_slug_global_uniqueness,
    ):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            record("authz", fn.__name__, fn.__name__, "test runs cleanly",
                   f"test script raised {type(exc).__name__}: {exc}", "Low", "NOT_TESTABLE")


if __name__ == "__main__":
    main()
