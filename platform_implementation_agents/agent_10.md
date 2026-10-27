# Agent 10 report — claude-sonnet-5-5 — 2026-10-27

## Scope accepted
Row 10 "review fixes": findings F-001…F-017 of `review/review_PLATFORM_SAAS_PLAN.md`, test-first, in its §8 order. Phase F not started. `review/` untouched. Nothing committed.

## What I fixed
| Finding | Fix | Permanent test |
|---|---|---|
| F-005 | New `platform_users.email_verified_at` (migration `b3d7f1a9c5e2`; SSO-only accounts backfilled as verified). `PlatformAuthService.claim_by_idp`: when SCIM link or SSO sign-in meets an **unverified** account, its password, TOTP + recovery codes, personal tokens and sessions are dropped, then it is marked verified; verified accounts keep credentials. Invite **by id** needs a verified address (403 `email_not_verified`) and the pending list is empty until then; accepting by the e-mailed link marks the address verified. | `tests/api/test_account_hijack.py` |
| F-002 | `platform_authz.ORG_ROUTES_SESSION_ONLY` enforced in `org_context` (org delete/cancel, member role/remove, transfer, project transfer, checkout, portal → 403 `session_required`). `POST /orgs` and invitation accepts need `write` scope. | `tests/api/test_token_org_limits.py` |
| F-001 | `tests/api/_routes.py` walks `effective_route_contexts()` and asserts > 100 routes; access-matrix and org-route-table tests use it. It found one unlisted route, `GET /.well-known/oauth-protected-resource` (public by design), now in `PUBLIC`; added a stale-entry check and "every org route uses `org_context`". | `test_access_matrix.py`, `test_org_invariants.py` |
| F-014 | `OrganizationService._refuse_if_locked` in project and token limit checks → 423. | `tests/api/test_org_deletion_lock.py` |
| F-003 | App-wide dependency `app/api/input_guard.py`: NUL in path, query, JSON or form body → 422. | `tests/api/test_nul_input.py` |
| F-013 | `allow_mcp` enforced at MCP token creation (402 `mcp_not_in_plan`, after the cap check so `mcp_token_limit` is unchanged) and at MCP use. | `tests/api/test_plan_allow_mcp.py` |
| F-012 | New migration `c8a4e6b2d9f1` adds legacy project members to the project's org as `member` (idempotent; downgrade is a no-op). | `test_migrations.py` |
| F-009 | Sanitizer unit tests (mutation `_FORBIDDEN_DETAIL_KEYS = ()` now fails). | `tests/unit/test_audit_sanitizer.py` |
| F-008 (part) | `POST /admin/sso/domains/{domain}/release` (platform admin, reason, audited `admin.sso_domain_released`; switches SSO off if it was the last verified domain). | `tests/api/test_sso_domain_release.py` |
| F-004 | Signed events with non-dict `data`/`object` are acknowledged as `ignored`. | `test_billing_webhooks.py` |
| F-006 | `require_admin` refuses tokens without a second factor when `admin_mfa_required` (403 `mfa_required`). Test `client_for` admin sessions now carry `amr=["pwd","otp"]`. | `test_mfa.py` |
| F-010 | Member list omits `last_login_at` / `mfa_enabled` for other people when the viewer is a plain member (own row kept); UI shows "—". | `test_org_console_api.py` |
| F-011 | `_deny` looks up the actor's e-mail when only the id is known. | `test_plan_enforcement.py` |
| F-015 | `organization_id` bound into the log context in `org_context` and `guard`, unbound per request. | `test_observability.py` |
| F-016 (part) | TS types: `AuditEntry.organization_id`, `EntityUpdate.name`. | tsc |

## What I skipped, and why
- **F-005 sign-up e-mail verification flow**: needs mail flows and a product decision. The fix above removes the exploit paths without it.
- **F-007** (support can run the SSO check): an existing test and the admin UI deliberately allow it; owner decision. `review/tests/test_adv_admin.py::test_support_is_read_only_everywhere` still fails because of it.
- **F-008 periodic TXT re-check**: failure policy (grace, who is locked out on a DNS blip) is a product decision and no scheduler exists.
- **F-016 rest**: `DELETE /admin/plans/{id}`, grandfathering, per-org envelope encryption, DB defaults/CHECKs on org tables, "Free · Free" label, `#/login` URL after sign-in.
- **mypy/ruff cleanup (F-017)**: kept no worse (mypy 10 = review's count, none in code I added; new files ruff-clean). Pre-existing errors left.

## Decisions to review
- F-012 consequence: orgs may now hold more members than their plan's seats; only new invites are blocked.
- Existing non-SSO accounts are unverified until they use an invite link, SSO or SCIM; until then they cannot accept invites by id (they can use the link).
- Test helper `make_user` sets `email_verified_at`; `client_for` admin sessions carry otp.

## Gates
- `uv run pytest tests/api tests/unit -q`: **2047 passed, 2 skipped** (was 1978 / 2).
- `review/tests`: 93 passed, 2 failed (was 82 / 13). Remaining: F-007 (skipped, above) and `test_adv_prehijack::test_B…`, whose own premise ("attacker sees a pending invite") no longer holds; the attacker now sees none, which is the fix. Ran without `dump_routes.py`, which writes into `review/`.
- mypy 10 errors (review baseline 10). ruff: new files clean.
- `npx tsc -b` clean; `npm run lint` 57 warnings, 0 errors; `npx vite build` OK.
- Alembic head is now `d1f5a7c3e9b2`. No new dependencies.

## Improvement scope — out of current phase
Phase F should add its RLS tests on top of `tests/api/_routes.py`.

## Follow-up pass (code-review findings)

Tests: `tests/api/test_followup_hardening.py`, plus additions to `test_sso_config.py` and `unit/test_oidc.py`.

- SCIM deactivate/DELETE now sync Stripe seats.
- Org deletion removes the org's SSO domains/connection/login requests and SCIM directory, users and groups.
- OIDC `email_verified`: a missing claim is refused unless the connection sets `trust_unverified_email`
  (new migration `d1f5a7c3e9b2`: off for new connections, on for existing OIDC ones so nothing breaks;
  toggle in the org SSO tab). An explicit `false` is always refused.
- Outbound IdP fetches connect to the address that was checked (DNS rebinding).
- SCIM cannot change the e-mail of an account that has a password, another team org or another directory (409).
- Signed-in TOTP enable/disable/regenerate count wrong codes and lock (429 `too_many_attempts`).
- Mail subject newlines collapsed; header errors are a failed send. SCIM limiter blocks before auth.
- Deletion job isolates failures and skips orgs that took a Stripe subscription. DNS errors mean "no records".

## HANDOFF: continue at row 11 — Phase F (RLS behind a flag, impersonation, per-org export, docs/); read `agent-orch/trigger_and_report_here.md` and this report first
