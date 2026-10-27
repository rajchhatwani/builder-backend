# Independent review: PLATFORM_SAAS_PLAN.md implementation (agents 1–9)

Reviewer: independent audit agent. Date of runs: 2026-10-27. Branch `phase_A_to_B`, working tree uncommitted on top of `e0ab075`.
No product code, existing tests, agent reports or Keycloak code were changed. All new material is under `review/`.

## 1. Verdict

The work is mostly accurate and in sync with the plan through Phase E. The test counts and the Alembic head the agents reported are true, the schema matches §3, the role matrix matches §2.2/§8, and 18 of 20 safety mutations were caught by the existing suite. It is **not ready to merge as-is**:

- three High issues: the route-walking safety tests are vacuous under the installed FastAPI, API tokens can perform destructive org actions, and unverified sign-up allows account/invite pre-hijacking that SCIM/JIT "linking" makes worse;
- six Medium issues (a 500 on NUL bytes, `plans.allow_mcp` never enforced, the deletion lock can be bypassed by creating projects, and others);
- Phase F (RLS, impersonation, export, docs) is not built, as expected. Agent 10 has not started.

Counts: **Critical 0 · High 3 · Medium 6 · Low 8**.

## 2. What I ran

| Command | Result |
|---|---|
| `uv run pytest tests/api tests/unit -q` | **1978 passed, 2 skipped** in 282 s. Matches the claim. |
| `uv run ruff check .` | 96 errors repo-wide. In the 73 agent-touched `.py` files: 12 errors in 9 files (4 in `tests/api/conftest.py`, 1 in `app/main.py`), and 2 files need `ruff format`. `tests/api/test_organizations.py` (committed in Phase A) has 10 unfixed errors. |
| `uv run mypy app` | **10 errors** (HEAD has 4). Six are new since HEAD (`security.py:270`, `orgs.py:210`, `admin_service.py` 625/669/673/703, `admin.py:554`). Agent 6 said all predated its row; agent 5 reported only 2. `admin_service.py:625` is guarded, no runtime bug. |
| `npx tsc -b` | clean |
| `npm run lint` | 57 warnings (the accepted ceiling), 0 errors |
| `npx vite build` | OK (675 kB main chunk warning) |
| Alembic | head = `a9c4e2f7b1d3`. `upgrade head` → `downgrade base` → `upgrade head` clean on an empty PG16. `alembic check` reports only index drift (5 migration-only indexes absent from the models, incl. `ix_organizations_deletion_due`). |
| Data migration test | Seeded 4 users / 3 projects / 3 project members at `a1b2c3d4e5f6`, upgraded, downgraded, re-upgraded: rows survive, personal orgs + `free` subscriptions backfilled, orphan project → `unclaimed-projects`. One invariant gap, see F-012. |
| `review/tests` (my scripts) | 95 tests: 82 passed, 13 failed. Each failure is a finding (map in §6). |
| Mutation spot-checks (scratch copy) | 20 mutants: 18 killed, 1 real survivor (F-009), 1 weak mutant. |
| Headless Chrome UI walk (built UI :5174 + API :8000, throwaway DB) | owner, member, platform admin (full MFA enrolment), anonymous, 375 px width, storage check. |
| `tests/e2e/test_generated_project.py` | Docker is available. The run had 18 dots (passes) and no failures when I stopped watching it, and it had not finished (it has an 840 s cap); log in `review/logs/e2e_generated_project.log`, so there is no final count. The e2e suite covers generated projects, not the platform org features, and no e2e test touches `/orgs` or `/admin`. The other e2e files (compose, keycloak) were not run. |

Not run: the platform-support and Okta/Entra/real-IdP/real-Stripe round trips (no credentials; agents also did not), the toggling of every journey as `platform_support` in the browser (covered via API in `test_adv_admin.py`), real authenticator-app scan.
New tooling installed outside the project: `puppeteer-core` in the scratchpad (Chrome at `/usr/bin/google-chrome-stable`). A throwaway Postgres container `review-pg` (port 55432) was used; the real database was never touched. Note: port 5173 is taken by an unrelated app, so the UI was served on 5174.

## 3. Findings

### High

**F-001 — The structural route-walk tests are vacuous (0 routes).**
Plan §5 ("a test walks the OpenAPI schema to catch new unlisted routes").
`tests/api/test_access_matrix.py:75-78` (`_routes()`), and `tests/api/test_org_invariants.py:204` (`test_every_org_route_has_a_required_org_role`).
FastAPI 0.156.8 wraps routers in `_IncludedRouter`, so `isinstance(r, APIRoute)` over `app.routes` yields **0** routes. Reproduce: `PYTHONPATH=. uv run python -c "from tests.api import test_access_matrix as t; print(len(t._routes()))"` → `0`. The "every route guarded", "guarded routes resolve to a project", the 401 unauthenticated sweep and the org-route-table completeness tests all pass trivially.
Real state, checked with my own enumerator (`review/tests/dump_routes.py`): 208 route+method pairs; all guarded except `GET /.well-known/oauth-protected-resource` (public by design, RFC 9728); `ORG_ROUTE_ROLES` is complete with no stale entries. So the property holds today, but nothing would catch a regression.
Fix: iterate `route.effective_route_contexts()` for `_IncludedRouter` (see my script) and add `assert len(routes) > 100`.

**F-002 — API tokens can perform destructive and owner-level org actions.**
Plan §8 (owner-only deletion), §4.3 session-only intent.
`app/api/security.py:331-355` (`org_context` only checks `read`/`write` scope); only SSO, SCIM and policies handlers call a session-only check.
A token with `write` scope called `DELETE /orgs/{slug}` → **202**: the org is locked and scheduled for deletion with all its projects. A `read`-only token called `POST /orgs` → **201**. Role changes, ownership transfer, member removal and billing checkout are in the same class.
Repro: `review/tests/test_adv_orgs.py::test_pat_cannot_use_session_only_routes` and `::test_read_only_pat_on_org_writes`.
Fix: require a session for org delete/cancel, transfer, role change, member removal and checkout; make `POST /orgs` require `write`.

**F-005 — Account pre-hijacking: sign-up never verifies the e-mail, and SCIM/JIT "link" the account; invites can be accepted by id.**
Plan §4.2 step 3 ("matches an existing platform_users row *linked to this org*"), §4.3, §8 invites.
No `email_verified` column or flow exists. Confirmed with `review/tests/test_adv_prehijack.py`:
(A) attacker registers `victim@<verified-domain>` first; the IdP later provisions the real victim; SCIM links the existing account into the org and **the attacker's password still signs in** (their old sessions also survive; `token_version` is not bumped). JIT does the same (`existing_account_outside_the_org_is_added_by_jit`).
(B) attacker registers the invitee's address, lists `GET /orgs/invitations/pending` and accepts `POST /orgs/invitations/{id}/accept` without ever seeing the e-mailed link. The accept-by-id feature (gap P1) removed the mailbox proof.
Fix: on linking via SCIM/JIT, invalidate the password (SSO-only hash), bump `token_version`, revoke sessions; require verified e-mail before accepting invites by id (or keep link-only); add e-mail verification at sign-up.

### Medium

**F-003 — NUL byte in a string field gives an unhandled 500, including on public endpoints.**
`app/services/platform_auth_service.py:178` (register), `organization_service.py:186` (org name), `scim_service.py:436` (SCIM `userName`).
`POST /account/register` with `a\x00b@example.com` raises `DBAPIError: invalid byte sequence 0x00`. Repro: `review/tests/test_adv_nul_and_unicode.py`, `test_adv_scim.py::test_scim_huge_and_hostile_bodies`. Fix: reject `\x00` in request validation (shared `str` validator or middleware).

**F-008 — A verified SSO/SCIM domain claim is permanent.**
`app/services/sso_service.py:395-460`. No re-verification, expiry or operator release endpoint; a legitimate new owner of the domain gets 409 `domain_taken`, and a former owner keeps SSO/SCIM rights over addresses on it. Design gap (not in plan). Fix: periodic re-check of the TXT record and an operator "release domain" action.

**F-009 — The audit `detail` sanitizer is untested.**
`app/services/audit_service.py:11-21` (`_clean_detail`). Setting `_FORBIDDEN_DETAIL_KEYS = ()` leaves 129 relevant tests green (mutation M09). This is the control the work queue cites for "never log tokens/passwords/secrets". My end-to-end canary test (`test_adv_secrets.py`) found no leak today. Fix: unit test that keys containing password/token/secret/authorization/cookie/otp are dropped.

**F-012 — Backfill leaves existing project members outside the project's org.**
Plan §3.2 ("project_members is a subset of the org"). After upgrade, a user who was an editor on someone else's project is a project member but not an org member (`organization_members` = 1 owner row per personal org). They keep project access, take no seat, and org offboarding/SCIM cannot remove them. Fix: in the migration, add such members to the org (or remove their project rows).

**F-013 — `plans.allow_mcp` is never enforced.**
Plan §3.1/§6.2. `grep allow_mcp app/` finds only the model and schemas. With `allow_mcp=false` and `max_mcp_tokens=50`, an `mcp:read` token is created (201). The operator Plans tab shows the flag, so it silently does nothing. Repro: `test_adv_plans.py::test_allow_mcp_false_is_enforced`. Agent 2 noted this; it is still open.

**F-014 — The deletion lock does not cover project creation or project-pinned tokens.**
Plan: locked org = 423 on every org and project route (agent 2b Round 2). After `DELETE /orgs/{slug}` (202), `POST /projects {organization_id: <locked org>}` returns **201** and `POST /account/tokens` pinned to a locked project returns **201** (`GET/PUT` on existing projects correctly give 423). Repro: `test_adv_plans.py::test_locked_and_deleting_org_blocks_writes_everywhere`.

### Low

- **F-004** A validly signed Stripe event whose `data.object` is not a dict raises `AttributeError` (500, Stripe retries). `stripe_webhook_service.py:112-119`. `test_adv_stripe.py`.
- **F-006** Admin access tokens are not checked for `amr` (MFA) in the guard; an `amr=["pwd"]` admin token is accepted on `/admin/users`. Enforcement is at login and refresh only, so exposure is bounded by access-token lifetime (§4.4).
- **F-007** `platform_support` can `POST /admin/organizations/{id}/sso/check` (live outbound fetch). Read-only in effect; contradicts "read-only" in the literal sense (§2.2).
- **F-010** `GET /orgs/{slug}/members` returns `mfa_enabled` and `last_login_at` to plain members. Plan §8 lists those columns under Admins. The member Plan page also shows usage counters and price.
- **F-011** `quota.denied` audit rows carry `actor_id` but no `actor_email`, so the org audit UI shows "session" as the actor (`organization_service.py:_deny`, called with `actor_email=None` from some paths). Plan §6.2 wants a clear deny log.
- **F-015** §9 "tenant-aware logs": only `request_id` is bound into the log context (`app/main.py:88`); no `organization_id` tag on log lines.
- **F-016** Smaller deviations: no `DELETE /admin/plans/{id}` (plan §7 says CRUD); plan edits are not grandfathered (§7; left as an open owner decision); secrets use one global Fernet key, not per-org envelope encryption (§9); `organizations`/`organization_members` have no server defaults and no CHECK on `role`/`kind`; `AuditEntry` TS type lacks `organization_id`, `EntityUpdate` lacks `name`; UI shows "Free · Free · active" and the URL stays `#/login` after sign-in.
- **F-017** The agents' repeated claim that mypy/ruff findings are "pre-existing" is only partly true (see §2).

Passed (checked, fine, one line each):
outsider gets 404 (indistinguishable from a missing org) on all 35 `/orgs/{slug}` routes for lower/UPPER/Mixed slugs; admin cannot create/demote/remove owners; member gets 403 with the owner's e-mail; last owner cannot leave or be demoted; personal org cannot be deleted; seat boundary (4 invites then 402) and 8-way concurrent invite race admit exactly one; concurrent accepts after a downgrade admit none; project cap 10/12 and a 6-way race admit one; token-cap race ≤ 3; `token_version` bump kills sessions; suspended user blocked; cross-org project join/transfer/read → 404; org audit never leaks other orgs and omits `detail`/IP; SCIM tenant isolation by guessed ids; 13 off-domain/homograph/suffix e-mails refused; malformed filters, paging and huge bodies give no 500 (except NUL); SCIM 429 after bad bearers; operator rotate then fresh token switches SCIM on; group-mapping limits and owner-mapping rule; Stripe signature variants, replay, out-of-order and customer mismatch; no secrets in audit rows, any DB column, logs or later GETs (canary test); operator views contain no secrets; support read-only on admin routes; wrong-audience tokens rejected; TOTP replay, recovery-code reuse (incl. format variants), lockout and challenge-token misuse all refused; SSO redirects are fixed app URLs; browser storage holds only `theme`; no horizontal overflow at 375 px; rate-limit message shown clearly.

## 4. Plan traceability

Status: Done / Partial / Missing / Deviates / Untested. "Test" = existing test unless noted.

| REQ | Requirement | Code | Test | Status |
|---|---|---|---|---|
| §2.1-1 | Organization incl. personal | `models/platform.py`, `organization_service.ensure_personal_org` | test_organizations | Done |
| §2.1-2 | Membership with role | `organization_members` | test_organizations | Done |
| §2.1-3 | Invitation (hashed token, expiry) | `organization_invitations` | test_org_console_api | Done |
| §2.1-4 | Project belongs to one org | `projects.organization_id NOT NULL` | test_migrations | Done |
| §2.1-5 | Plans seeded free/team/business/enterprise | migration `b2c3d4e5f6a7` | test_plan_enforcement | Done (extra `is_public`, `project_override`) |
| §2.1-6 | Subscription one row per org | `subscriptions` | test_billing_* | Done |
| §2.1-7 | SsoConnection/domains | `models/sso.py` | test_sso_config | Done |
| §2.1-8 | ScimDirectory | `models/scim.py` | test_scim | Done |
| §2.2-1 | Role matrix org/platform | `platform_authz.py` | test_org_invariants | Done |
| §2.2-2 | Admins can't make owners | `organization_service.update_member_role` | M10 mutant killed | Done |
| §2.2-3 | Support read-only | `ADMIN_PERMISSIONS` | M21 killed; `test_adv_admin` | Done (F-007) |
| §2.3 | Personal org: 1 owner, SSO/SCIM off | `ensure_personal_org`, 409 for SSO | test_sso_config | Done |
| §3.1 | New tables | migrations | test_migrations; my schema dump | Done (F-016 minor) |
| §3.2-1 | `projects.organization_id` NOT NULL | `c7e1f3a9d2b4` | test_migrations | Done |
| §3.2-2 | Project members ⊂ org | `member_service.py:46` | M16 killed | Partial (F-012 for legacy data) |
| §3.2-3 | Audit `organization_id`, `default_organization_id` | models | test_org_console_api | Done |
| §3.3 | RLS (Phase F) | none | none | Missing (Phase F) |
| §4.1 | Built-in auth kept | `platform_auth_service` | test_account | Done |
| §4.2-1 | Domain discovery | `/account/login/discover` | test_sso_login | Done |
| §4.2-2 | Assertion validation | `saml.py`, `oidc.py` | test_saml/oidc (wrapping, replay, nonce) | Done |
| §4.2-3 | JIT only for users linked to the org | `sso_service` | test_sso_login | Deviates (adds any existing account; F-005) |
| §4.2-4 | Session is normal JWT (`amr=sso`) | `sso_service` | test_sso_login | Done |
| §4.3-1 | SCIM Users/Groups/discovery | `api/scim.py` | test_scim, test_scim_protocol | Done |
| §4.3-2 | Deactivate: remove membership, bump token_version | `scim_service._leave` | test_scim | Done (signs out everywhere; open owner note) |
| §4.3-3 | Group → role dictionary | `scim_directories.group_roles` | test_scim; `test_adv_scim` | Done |
| §4.3-4 | Bearer shown once, hash stored | `bb_scim_` | test_scim; canary test | Done |
| §4.4-1 | TOTP all users | `core/totp.py`, `mfa_service` | test_mfa; `test_adv_mfa` | Done |
| §4.4-2 | Platform staff MFA always | login/refresh | test_mfa | Done (guard has no amr check: F-006) |
| §4.4-3 | Per-org require-MFA | `org_context`, `guard`, MCP | M12 killed | Done |
| §4.4-4 | WebAuthn/passkeys | none | none | Missing (Phase 2 of §4.4, no row) |
| §4.5 | Impersonation | none | none | Missing (Phase F) |
| §5-1 | Default-deny org route table | `ORG_ROUTE_ROLES`, `org_context` | test_org_invariants | Done in code; test vacuous (F-001) |
| §5-2 | Set LOCAL app.organization_id | none | none | Missing (Phase F) |
| §6.2-1 | Seat check inc. pending, locked row | `enforce_seat_limit` | M04 killed; race tests | Done |
| §6.2-2 | Projects, API/MCP tokens | `enforce_*_limit` | M05/M19/M20 killed | Done |
| §6.2-3 | `allow_sso`, `allow_scim` gates | `_require_sso_allowed` | test_sso_config, test_scim | Done |
| §6.2-4 | `allow_mcp` | none | none | Missing (F-013) |
| §6.2-5 | 402 + deny audit | `_deny` | test_plan_enforcement | Done (F-011) |
| §6.3 | Webhook sync, downgrade soft-fail | `stripe_webhook_service` | test_billing_webhooks; M07 killed | Done (F-004) |
| §6.4 | High-water-mark seats | `billing_service.sync_seats` | test_billing_seats | Done |
| §6.5 | Seat override with reason, audited | admin org patch | test_admin_orgs_billing | Done |
| §7-1 | Organizations tab incl. detail | `/admin/organizations` | test_admin_orgs_billing | Done |
| §7-2 | Plans CRUD, grandfathering | `PUT /admin/plans` | test_admin_orgs_billing | Partial (no delete; no grandfathering) |
| §7-3 | Billing, Insights, audit filters | admin routes | same | Done |
| §7-4 | Impersonation | none | none | Missing (Phase F) |
| §7.1 | Operators never see secrets | admin schemas | `test_adv_admin` canary | Done |
| §7.1-2 | Impersonation consent toggle | none | none | Missing (Phase F) |
| §8-1 | Org console People/Invites/Projects/Plan/SSO&SCIM/Security/Audit | `frontend/src/pages` | headless walk | Done |
| §8-2 | Member read-only + "ask your admin" with owner e-mail | `org_forbidden` | walk + `test_adv_orgs` | Done |
| §8-3 | Members see no billing details / 2FA columns | `OrganizationMemberRead` | `test_adv_orgs` | Deviates (F-010) |
| §8-4 | Org-scoped audit, no leakage | `audit_service` | M15 killed | Done |
| §8.1 | Routes `#/org/<slug>[/plan|/sso|/policies|/audit]` | `App.tsx` | walk | Done |
| §9-1 | Tenant filter in SQL + Python | services | access matrix (partly vacuous) | Done |
| §9-2 | Tenant-aware logs | only request_id | none | Missing (F-015) |
| §9-3 | Per-org encrypted secrets | global Fernet | test_sso_config | Deviates (F-016) |
| §9-4 | `GET /org/<slug>/export`, pen test | none | none | Missing (Phase F) |
| §10 | Checkout, webhook, portal, past_due | `billing_service` | test_billing_* | Done (Stripe never run for real) |
| §11 | docs/MULTITENANT_ARCHITECTURE, SSO_SETUP, SCIM_SETUP | none (`docs/` absent) | none | Missing (Phase F) |
| §12.A–E | Phases A–E | as above | | Done except as listed |
| §12.F | RLS, pen test, impersonation, export, SOC 2 | none | none | Missing (row 10 not started) |

Route coverage: all 208 routes in `/openapi.json` are guarded (see F-001 for the one public discovery route); the access-matrix PUBLIC list has no stale entries; every `/orgs/{slug}/…` route is in `ORG_ROUTE_ROLES`.

## 5. Agent-report accuracy

| Claim | Verdict |
|---|---|
| 1978 passed, 2 skipped | **True** |
| Alembic head `a9c4e2f7b1d3` | **True** |
| `npm run lint` = 57 warnings, tsc/vite clean | **True** |
| "Mutations caught" (agents 5, 8) | Largely true; my independent 20 mutants agree (18 killed). One real survivor (audit sanitizer) |
| "ruff clean on every file I touched" | Mostly true; `tests/api/conftest.py` long lines acknowledged; `test_organizations.py` has 10 errors from Phase A |
| mypy errors "pre-existing" (agent 6) | **Partly false**: HEAD has 4, tree has 10 |
| "a test walks the routes" (conventions, agents 1, 2, 5, 8) | **False in effect**: the walkers see 0 routes (F-001) |
| Agent 4b: "all 12 response types match OpenAPI" | **True** by my drift script (74/108 names matched; only `AuditEntry.organization_id`, `EntityUpdate.name` differ) |
| Agent 9: "clicked through, no storage of the SCIM token" | Plausible; I verified storage is only `theme` (SCIM section not exercised as that needs an enterprise IdP) |
| Agent 7: admin console signs in again | **True** (I enrolled TOTP and reached every admin tab) |
| Agent 8: operator rotation never shows the token; fresh token switches SCIM on | **True** |
| Agent 2: `allow_mcp` not checked separately, "counter does the job" | Misleading: with a non-zero cap the flag is ignored (F-013) |
| Agent 3/2b: soft-fail downgrades, past_due blocks seats/projects | **True** |
| Row 4/4d "not clicked through in a browser" | Honest; my walk found no broken screens |
| Queue ticks rows 1–9 | Accurate for what is built; row 10 correctly unticked. Open owner decisions (grandfathering, free-plan numbers) remain open and are honestly listed |

## 6. Test gaps and review scripts (all under `review/tests/`)

Run from the repo root with a disposable DB, for example:
`TEST_DATABASE_URL=postgresql+asyncpg://…/review_test PYTHONPATH=. BUILDER_ENVIRONMENT=local uv run python -m pytest review/tests -p no:cacheprovider -q`
(`dump_routes.py` must be run first to create `review/artifacts/routes.json`.)

| Script | Covers | Failing = finding |
|---|---|---|
| `dump_routes.py` | real route enumeration, guard classification, org table completeness | F-001 evidence |
| `test_adv_orgs.py` | outsider 404 sweep, role abuse, PAT misuse, seat/project/token races, IDOR, input edge cases, member visibility | F-002, F-010 |
| `test_adv_scim.py` | tenant isolation, off-domain provisioning, filters, paging, hostile bodies, offboarding, seat race, rotation, mappings | F-003 |
| `test_adv_stripe.py` | signatures, malformed signed events, out-of-order, audit hygiene | F-004 |
| `test_adv_admin.py` | support read-only, audiences, admin amr, operator secret canaries | F-006, F-007 |
| `test_adv_secrets.py` | secrets in audit/DB/logs/GETs | (passes) |
| `test_adv_mfa.py` | replay, recovery reuse, lockout, challenge misuse | (passes) |
| `test_adv_prehijack.py` | unverified sign-up + SCIM link + invite-by-id | F-005 |
| `test_adv_plans.py` | `allow_mcp`, seat override, deletion lock | F-013, F-014 |
| `test_adv_nul_and_unicode.py` | NUL / odd Unicode | F-003 |
| `mutate.py` | 20 mutants in a scratch copy | F-009 |
| `types_drift.py` | frontend types vs OpenAPI | F-016 |
| `seed_staff.py` | creates staff users in the review DB only | tooling |

Existing-suite gaps: no test for `_clean_detail`; no test that creating a project in a locked org is refused; no test for PAT access to destructive org routes; no non-vacuous route walker; no email-verification tests; no concurrency test for SCIM seat creation was in the suite (mine passes); no frontend test runner at all.

## 7. Not yet built / out of scope (not defects)

Phase F (row 10, agent 10 not started): Postgres RLS and `SET LOCAL app.organization_id`; impersonation, its banner and the per-org consent toggle (§4.5, §7.1, §8); per-org export; `docs/MULTITENANT_ARCHITECTURE.md`, `SSO_SETUP.md`, `SCIM_SETUP.md`; pen test and SOC 2 evidence. Also: WebAuthn/passkeys (§4.4 Phase 2), "enforce SSO" policy, a Stripe reconciliation scheduler (job exists, no scheduler), real-IdP and real-Stripe verification, Okta/Entra SCIM validators.

## 8. Recommended fix order

1. F-005 pre-hijacking (invalidate password and sessions on SCIM/JIT link; stop invite-by-id without verified e-mail).
2. F-002 session-only gate for delete/transfer/role/remove/checkout; scope-check `POST /orgs`.
3. F-001 repair the route walkers and add a non-empty assertion, then rerun; this also protects every later phase.
4. F-014 close the deletion-lock hole on project and token creation.
5. F-003 reject NUL bytes at the validation layer.
6. F-013 enforce `plans.allow_mcp`, or remove the flag from the Plans tab.
7. F-012 backfill project members into their org (a new migration; do not edit applied ones).
8. F-009 add the sanitizer unit test; F-008 domain re-verification and operator release.
9. Low items: F-004, F-006, F-007, F-010, F-011, F-015, F-016, mypy/ruff cleanup.
10. Only then start Phase F; make RLS tests part of the same route-walker.
