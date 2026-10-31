"""Mutation spot-checks in a SCRATCH COPY (never the working tree).
For each mutation: copy file -> apply textual change -> run the named tests -> expect failures -> restore.
Survivors (all selected tests still pass) are reported.

Run:  uv run python review/tests/mutate.py <scratch_copy_dir> [mutation_id ...]
The scratch copy is made by:  rsync -a --exclude .venv --exclude node_modules --exclude frontend --exclude .git --exclude review ./ <dir>/
Needs TEST_DATABASE_URL pointing at a disposable DB.
"""
import os
import pathlib
import subprocess
import sys

SCR = pathlib.Path(sys.argv[1])
ONLY = set(sys.argv[2:])
PY = "/mnt/files/projects/builder-backend/.venv/bin/python"

M = [
    ("M01 org role gate always true", "app/core/platform_authz.py",
     "return ORG_ROLE_LEVEL[role] >= ORG_ROLE_LEVEL[needed]", "return True",
     ["tests/api/test_organizations.py", "tests/api/test_org_console_api.py", "tests/api/test_org_invariants.py"]),
    ("M02 last-owner guard off", "app/services/organization_service.py",
     "        if not others:\n            raise AppError(\n                code=\"last_owner\"", "        if False:\n            raise AppError(\n                code=\"last_owner\"",
     ["tests/api/test_organizations.py", "tests/api/test_org_console_api.py", "tests/api/test_org_invariants.py", "tests/api/test_scim.py"]),
    ("M03 token_version not checked", "app/services/access_service.py",
     'or claims.get("tv") != user.token_version', "or False",
     ["tests/api/test_account.py", "tests/api/test_access_matrix.py", "tests/api/test_mfa.py"]),
    ("M04 seat cap off-by-one", "app/services/organization_service.py",
     "if cap is not None and used + extra > cap:", "if cap is not None and used + extra > cap + 1:",
     ["tests/api/test_plan_enforcement.py", "tests/api/test_billing_seats.py", "tests/api/test_organizations.py"]),
    ("M05 project cap off-by-one", "app/services/organization_service.py",
     "if cap is not None and used + 1 > cap:", "if cap is not None and used + 1 > cap + 1:",
     ["tests/api/test_plan_enforcement.py", "tests/api/test_organizations.py"]),
    ("M06 invite email match off", "app/services/organization_service.py",
     "if normalize_email(user.email) != row.email:", "if False:",
     ["tests/api/test_org_console_api.py", "tests/api/test_organizations.py"]),
    ("M07 stripe stale check off", "app/services/stripe_webhook_service.py",
     "if created < await self._newest_applied(org_id):", "if False:",
     ["tests/api/test_billing_webhooks.py"]),
    ("M08 totp replay check off", "app/services/mfa_service.py",
     "last_step=user.totp_last_step", "last_step=None",
     ["tests/api/test_mfa.py"]),
    ("M09 audit detail sanitizer off", "app/services/audit_service.py",
     '_FORBIDDEN_DETAIL_KEYS = ("password", "token", "secret", "authorization", "cookie", "otp")', "_FORBIDDEN_DETAIL_KEYS = ()",
     ["tests/api/test_admin.py", "tests/api/test_account.py", "tests/api/test_observability.py", "tests/api/test_service_coverage.py"]),
    ("M10 admins may make owners", "app/services/organization_service.py",
     "if OrgRole.owner in (member.role, role) and actor_role is not OrgRole.owner:", "if False:",
     ["tests/api/test_org_console_api.py", "tests/api/test_organizations.py", "tests/api/test_org_invariants.py"]),
    ("M11 org deletion lock off", "app/api/security.py",
     "summary.organization.deletion_requested_at is not None\n        and (method, template) not in authz.ORG_ROUTES_OPEN_DURING_DELETION",
     "False\n        and (method, template) not in authz.ORG_ROUTES_OPEN_DURING_DELETION",
     ["tests/api/test_org_deletion.py"]),
    ("M12 org MFA policy off", "app/api/security.py",
     "summary.organization.require_mfa\n        and not principal.mfa_satisfied", "False\n        and not principal.mfa_satisfied",
     ["tests/api/test_org_policies.py", "tests/api/test_mfa.py"]),
    ("M13 SSO settings allow PAT", "app/api/sso.py",
     'if ctx.principal.via != "session":', "if False:",
     ["tests/api/test_sso_config.py"]),
    ("M14 project member must be org member off", "app/services/member_service.py",
     'code="not_an_org_member"', 'code="not_an_org_member_X"',
     ["tests/api/test_organizations.py", "tests/api/test_org_console_api.py", "tests/api/test_access_matrix.py"]),
    ("M15 audit org filter dropped", "app/services/audit_service.py",
     "conditions.append(AuditLog.organization_id == organization_id)", "pass",
     ["tests/api/test_org_console_api.py", "tests/api/test_admin_orgs_billing.py", "tests/api/test_admin.py"]),
    ("M16 project member must be org member (real)", "app/services/member_service.py",
     "if in_org is None:", "if False:",
     ["tests/api/test_organizations.py", "tests/api/test_org_console_api.py", "tests/api/test_access_matrix.py", "tests/api/test_org_invariants.py"]),
    ("M17 SCIM verified-domain check off", "app/services/scim_service.py",
     "if verified is None:", "if False:", ["tests/api/test_scim.py"]),
    ("M18 past_due never refuses", "app/services/organization_service.py",
     "if sub.status is not SubscriptionStatus.past_due:", "if True:",
     ["tests/api/test_billing_webhooks.py", "tests/api/test_billing_lifecycle.py", "tests/api/test_plan_enforcement.py"]),
    ("M19 API token cap off", "app/services/organization_service.py",
     "if used + 1 > plan.max_api_tokens:", "if False:", ["tests/api/test_plan_enforcement.py", "tests/api/test_mcp.py"]),
    ("M20 MCP token cap off", "app/services/organization_service.py",
     "if used + 1 > plan.max_mcp_tokens:", "if False:", ["tests/api/test_plan_enforcement.py", "tests/api/test_mcp.py"]),
    ("M21 support gets users:write", "app/core/platform_authz.py",
     '{"users:read", "projects:read", "audit:read", "stats:read", "settings:read"}',
     '{"users:read", "users:write", "projects:read", "audit:read", "stats:read", "settings:read"}',
     ["tests/api/test_admin.py", "tests/api/test_admin_orgs_billing.py", "tests/api/test_authorization.py"]),
    # -- Phase F -------------------------------------------------------------------------
    ("M22 impersonation: org consent not re-checked", "app/services/access_service.py",
     "or not org.allow_impersonation", "or False", ["tests/api/test_impersonation.py"]),
    ("M23 impersonation: writes always allowed", "app/core/platform_authz.py",
     'return None if writes_allowed else "impersonation_read_only"', "return None",
     ["tests/api/test_impersonation.py", "tests/api/test_access_matrix.py"]),
    ("M24 impersonation: other orgs reachable", "app/api/security.py",
     "if organization_id != info.organization_id:", "if False:", ["tests/api/test_impersonation.py"]),
    ("M25 impersonation: never-list empty", "app/core/platform_authz.py",
     '_IMPERSONATION_NEVER: tuple[str, ...] = ("/tokens", "/auth/secrets", "/export", "/billing/")',
     "_IMPERSONATION_NEVER: tuple[str, ...] = ()",
     ["tests/api/test_impersonation.py", "tests/api/test_access_matrix.py"]),
    ("M26 export open to members", "app/core/platform_authz.py",
     '("GET", "/orgs/{slug}/export"): OrgRole.owner,', '("GET", "/orgs/{slug}/export"): OrgRole.member,',
     ["tests/api/test_org_export.py", "tests/api/test_access_matrix.py"]),
    ("M27 guard no longer binds the RLS scope", "app/api/security.py",
     "await rls.bind(db, organization_id)  # §3.3: the rest of the request sees this org only", "pass",
     ["tests/api/test_rls.py", "tests/api/test_access_matrix.py"]),
    ("M28 RLS scope is SET, not SET LOCAL", "app/core/rls.py",
     "SELECT set_config('app.organization_id', :org, true)", "SELECT set_config('app.organization_id', :org, false)",
     ["tests/api/test_rls.py"]),
    ("M29 consent withdrawal leaves sessions open", "app/services/impersonation_service.py",
     "            row.ended_at = now\n            await self._audit_ended(row, by, why, RequestInfo())\n            count += 1",
     "            count += 1", ["tests/api/test_impersonation.py"]),
    ("M30 viewing token not bound to its member", "app/services/access_service.py",
     "or row.target_user_id != target.id", "or False", ["tests/api/test_impersonation.py"]),
    ("M31 viewing token not bound to its operator", "app/services/access_service.py",
     'or str(claims.get("imp_by")) != str(row.operator_id)', "or False", ["tests/api/test_impersonation.py"]),
    ("M32 export is not audited", "app/api/orgs.py",
     '"org.exported",', '"org.exported_x",', ["tests/api/test_org_export.py"]),
    ("M33 staff can be viewed as", "app/services/impersonation_service.py",
     "or target.platform_role is not PlatformRole.customer", "or False", ["tests/api/test_impersonation.py"]),
    ("M16x placeholder", "app/services/scim_service.py",
     None, None, ["tests/api/test_scim.py"]),  # placeholder, filled below
]

env = dict(os.environ, PYTHONPATH=str(SCR), BUILDER_ENVIRONMENT="local")
results = []
for mid, rel, old, new, tests in M:
    if ONLY and mid.split()[0] not in ONLY:
        continue
    if old is None:
        continue
    f = SCR / rel
    src = f.read_text()
    if old not in src:
        results.append((mid, "PATTERN NOT FOUND"))
        continue
    f.write_text(src.replace(old, new, 1))
    try:
        p = subprocess.run([PY, "-m", "pytest", *tests, "-p", "no:cacheprovider", "-q", "-x", "--no-header", "-W", "ignore", "--tb=no"],
                           cwd=SCR, env=env, capture_output=True, text=True, timeout=900)
        tail = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else p.stderr[-200:]
        results.append((mid, "KILLED" if p.returncode != 0 else "SURVIVED", tail))
    finally:
        f.write_text(src)
    print(results[-1], flush=True)
print("\nSUMMARY")
for r in results:
    print(r)
