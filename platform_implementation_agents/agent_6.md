# Agent 6 report — claude-opus-5-5 — 2026-10-27

## Scope accepted
Queue row 6, Phase D.5–D.7 + §4.4 Phase 1 + §8 Security policies. Before starting, the owner asked
for a dedicated frontend agent (agent 7) to build the UI for everything so far. So I **split row 6**:
row 6 is the backend (this report), and a new **row 7** covers the frontend for rows 5 + 6 plus a
backend↔frontend sync audit. SCIM is now row 8 and Phase F row 9.

I waited for agent 5 (session `builder-backend-5c`) to tick row 5 and write its HANDOFF before
touching the tree. We coordinated over cross-session messages.

Baseline before changes: `tests/api tests/unit` → **1847 passed, 2 skipped**.

## What was already done
- Rows 1–5: orgs, plans/quotas, Stripe, org console UI, org deletion, SSO backend (SAML + OIDC, DNS
  domains, discovery, JIT, `allow_sso`). See `agent_1.md` … `agent_5.md`.
- No MFA, session policy, SSO test or operator SSO status existed before this row.

## Research notes / decisions
- **TOTP** is RFC 6238 (SHA-1, 6 digits, 30 s, ±1 step), written by hand in `app/core/totp.py`
  (about 100 lines, checked against the RFC 6238 Appendix B vectors). **No new dependency.**
- **Replay:** the last accepted step is stored (`totp_last_step`), and a code for that step or an
  earlier one is refused.
- **Brute force:** a wrong code counts toward the same lockout as a wrong password. A correct
  password **does not** reset the counter while a code is still due, because otherwise re-entering
  the password would buy unlimited code guesses. There's a test for this.
- **MFA challenge:** an HS256 JWT with its own audience (`builder-mfa`), lasting 5 minutes. It is
  bound to `token_version`, to the surface (`for`: app/admin) and to the purpose (`pur`:
  verify/enroll). No route accepts it as a bearer token.
- **Platform staff, "MFA at all times" (§4.4):** this applies to admin **and** support, on both the
  admin console and the customer app.
  - A staff member without TOTP gets an *enrolment* challenge. It can set up TOTP, but it can never
    sign in by itself.
  - Admin refresh also refuses a login family that didn't use a second factor, so sessions from
    before this change end at their next refresh.
  - `BUILDER_ADMIN_MFA_REQUIRED=false` is an escape hatch for local development only.
- **`amr`:** every login family stores `auth_methods` (`pwd`, `pwd otp`, `pwd rc`, `sso`). It is
  copied into each access token's `amr` claim, survives refresh and password change, and
  `Principal.mfa_satisfied` reads it.
- **SSO and "require MFA" (agent 5's question):** an SSO session counts as MFA, because the IdP
  owns the second factor (`amr = sso`).
  - SSO-only accounts can't set up TOTP (409 `sso_only_account`).
  - An API token passes the MFA policy if its owner has TOTP on or is an SSO-only account.
- **Org MFA policy:** checked on every org route (`org_context`), every project route (`guard`) and
  every **MCP tool call**. The exceptions are `GET /orgs/{slug}` (so the UI can explain the block)
  and leaving the org.
  - The answer is 403 `org_mfa_required`, with the org and `mfa_enabled` in `details`.
  - An admin can only turn the policy on from an MFA'd session (409 `enable_mfa_first`), so nobody
    locks themselves out.
  - While an org requires MFA, its members can't turn TOTP off (409 `mfa_required_by_org`).
- **Session TTL (§8 "default session TTL"):**
  - It is an *absolute* cap counted from sign-in (`family_started_at`), however often the refresh
    token rotates, and it caps the cookie's max-age.
  - With several orgs, the strictest one wins.
  - Range is 1–720 hours; `null` means the platform default (14 days).
  - It applies only to customer-app sessions; the admin console keeps its own 12-hour cap.
- **"Test with my own e-mail" (D.6):**
  - `POST /orgs/{slug}/sso/test` returns a login URL. It carries a 5-minute signed ticket naming the
    admin and the org.
  - The IdP round trip uses the normal binding cookie and the single-use login state, with a new
    `purpose = 'test'`. It works **before activation**.
  - A test never mints a session and never runs JIT. It records `ok` / `email_mismatch` /
    `email_domain_not_verified` / the failure reason (`bad_signature`, …) on the connection, audits
    `sso.test`, and redirects to `#/org/<slug>/sso?sso_test=<result>`.
  - A SAML Response that fails validation can't say which request it answers. If the browser has a
    test pending, the failure becomes that test's result. The browser binding makes this safe, and
    the only effect is recording a result.
- **Operator test button (D.5):** it is a configuration *check*, because an operator can't sign in
  at a customer's IdP. It covers plan, verified domain, config, active, certificate expiry (warning
  under 30 days), OIDC client secret, discovery and JWKS (both fetched live), and the last test. The
  same check is available to org admins at `POST /orgs/{slug}/sso/check`.

## Implementation summary
- `alembic/versions/f5c3a8e1b7d9_mfa_and_security_policies.py` — **new Alembic head** (after
  `e4b9c2d7a1f5`):
  - `platform_users.totp_secret_enc / totp_enabled_at / totp_last_step`;
  - table `mfa_recovery_codes` (SHA-256 hashes);
  - `platform_refresh_tokens.auth_methods / family_started_at`;
  - `organizations.require_mfa / session_ttl_hours` (CHECK 1–720);
  - `sso_login_requests.purpose` (CHECK login|test) `/ test_user_id`;
  - `sso_connections.last_test_at / last_test_result / last_tested_by`.
  - It downgrades cleanly.
- `app/core/totp.py` (new): codes, verify with drift and replay, otpauth URI, recovery codes.
- `app/services/mfa_service.py` (new):
  - sign-in steps (verify / setup + enable with a challenge);
  - signed-in setup / enable / disable / regenerate codes;
  - status;
  - operator reset.
  - The secret is encrypted with `app.core.crypto`. Secrets, codes and tokens are never audited.
- `app/services/platform_auth_service.py`:
  - `login()` now returns `Session | MfaChallenge`;
  - `finish_login()`;
  - `_start_session(methods, family_started_at)` with the org TTL cap;
  - refresh keeps the methods, refuses staff families without MFA, and applies the cap;
  - `issue_session(methods="sso")`;
  - `change_password` keeps the session's methods.
- `app/core/platform_security.py`: `AUDIENCE_MFA`, `MFA_METHODS`, `SSO_ONLY_PASSWORD_HASH` (moved
  here from `sso_service`, which re-exports it), and an `amr` argument on `access_claims`.
- `app/services/access_service.py`: `Principal.auth_methods` from `amr`, and
  `Principal.mfa_satisfied`.
- `app/api/account.py`:
  - `POST /account/login` → `SessionRead | MfaChallengeRead`;
  - `POST /account/login/mfa`, `/login/mfa/setup`, `/login/mfa/enable`;
  - `GET /account/mfa`;
  - `POST /account/mfa/totp/setup|enable|disable`, `/account/mfa/recovery-codes`.
  - Code errors are **422** on signed-in routes, so the app doesn't read them as "session
    expired".
- `app/api/admin.py`:
  - `/admin/login` (same union) and `/admin/login/mfa|/mfa/setup|/mfa/enable`;
  - `POST /admin/users/{id}/reset-mfa {reason}` (users:write; refuses your own account);
  - `POST /admin/organizations/{id}/sso/check` (projects:read; audited `admin.sso_checked`);
  - SSO status + policy fields on `AdminOrgRead`, and `mfa_enabled` on `AdminOrgMemberRead`.
- `app/api/orgs.py`: `GET|PATCH /orgs/{slug}/policies`; `require_mfa` / `session_ttl_hours` on
  `OrganizationRead`; `mfa_enabled` on `OrganizationMemberRead` (§8 People "2FA on/off").
- `app/api/security.py`: `org_mfa_required()` 403, enforced in `org_context` and `guard`.
  `platform_authz`: new org routes and `ORG_ROUTES_OPEN_WITHOUT_MFA`.
- `app/services/sso_service.py`:
  - `create_test`, test tickets, `purpose`-aware `start_login` / `finish_saml` / `finish_oidc`,
    which now return `SsoOutcome` (session **or** test result);
  - `check()`;
  - an inactive connection only serves the test this browser started (normal logins still get
    `sso_unavailable`).
  - `app/api/sso.py`: `POST /orgs/{slug}/sso/test`, `POST /orgs/{slug}/sso/check`, `last_test` on
    `GET /orgs/{slug}/sso`, and the redirect to `#/org/<slug>/sso?sso_test=…`.
- `app/services/admin_service.py`: `org_sso()`.
- `app/services/mcp_service.py`: **pre-existing gap closed.** MCP tools only checked project
  membership. They now also check org membership, the deletion lock (423) and the MFA policy.
- `.env.example`: `BUILDER_ADMIN_MFA_REQUIRED`, `BUILDER_MFA_CHALLENGE_SECONDS`,
  `BUILDER_TOTP_ISSUER`.

## Tests I wrote (TDD: red first, then green)
- `tests/unit/test_totp.py` (18): RFC 6238 vectors, drift, replay, malformed codes, URI, recovery
  codes.
- `tests/api/test_mfa.py` (24): enrolment, encrypted storage, no secrets in audit, code step,
  replay, recovery codes, lockout (including the "password doesn't reset it" case), challenge
  binding (token_version, surface, purpose), disable/regenerate, SSO-only accounts, staff
  enrolment on both surfaces, staff can't disable, admin refresh without MFA, operator reset +
  permissions.
- `tests/api/test_org_policies.py` (12): read/update permissions, `enable_mfa_first`, TTL bounds,
  session-only, enforcement on org + project routes, SSO sessions, API tokens, disable blocked by
  org, People 2FA column, TTL cap + absolute expiry, strictest org wins.
- `tests/api/test_sso_test_and_check.py` (12): SAML test before activation (no session, no JIT),
  `email_mismatch`, bad signature as the test result, OIDC test, ticket bound to org + expiry +
  forgery, permissions/config, inactive connection still refuses normal logins, SAML/OIDC/empty
  checks, operator status column + check + audit, operator member 2FA.
- `tests/api/test_mcp.py` (+2): MCP refuses an org that requires MFA and a locked org.
- `tests/api/test_migrations.py` (+1): new columns, CHECKs, round trip.
- Updated: 3 admin sign-in tests in `test_admin.py` (they now enrol TOTP through the new steps);
  the MCP viewer test now adds the viewer to the org (it had built an impossible state).
  `tests/api/conftest.py` gained `totp_clock` and `bearer_for(amr=…)`; `tests/api/_mfa_helpers.py`
  is new.
- **Mutation checks** (each mutant must turn the suite red):
  - TOTP replay check removed — caught;
  - challenge surface/purpose check removed — **survived at first**, so I added
    `test_a_staff_customer_app_challenge_does_not_open_the_admin_console`; now caught;
  - org MFA enforcement on projects removed — caught;
  - session-TTL cap removed — caught;
  - SSO test e-mail comparison removed — caught;
  - staff refresh-without-MFA check removed — caught;
  - staff enrolment requirement removed — caught.

## Test run result
`uv run pytest tests/api tests/unit -q` → **1916 passed, 2 skipped, 62 warnings in 232s** (baseline 1847 → +69 new tests).
ruff check/format: clean on every file I touched, apart from four pre-existing long lines in
`tests/api/conftest.py` (lines 51–54). mypy on the touched app files: 10 errors, **all on lines that
predate this row** (`stripe_client.py:86`, `security.py:270`, `admin_service.py` 313/593/637/641/671,
`orgs.py` 210/581, `admin.py` 554); none in new code. Frontend not touched (row 7).

## Improvement scope — out of current phase
- WebAuthn/passkeys (§4.4 Phase 2).
- "Remember this device" for MFA; e-mailing the user when MFA is turned off or reset.
- The per-org "allow operator impersonation" toggle (§8 Security policies) belongs with
  impersonation in row 9.
- An "enforce SSO for the domain" policy (refuse password login), already noted by agent 5.
- `GET /projects` could flag projects of orgs whose MFA policy the session doesn't meet, as it does
  for locked orgs. Today the 403 comes when the project is opened.
- MCP `list_projects` still lists projects of locked or MFA-requiring orgs; the tools refuse them.
- The challenge token isn't single-use: replaying it needs a *new* valid code within 5 minutes, and
  failures count toward the lockout. A jti blocklist would make it strictly one-shot.
- The DNS-rebinding gap in the SSRF guard (agent 5) also affects the new OIDC check.

## Open items / known issues
- **Breaking until row 7 ships:** the admin console UI expects `/admin/login` to return a session.
  Staff now get an MFA challenge, so **the current admin UI can't sign in**. Row 7 item P0-1 fixes
  this. Until then, set `BUILDER_ADMIN_MFA_REQUIRED=false` locally.
- The bootstrap admin follows the same rule: at first sign-in it sets up TOTP, then changes the
  temporary password (`must_change_password`).
- `tests/e2e` (needs Docker Compose) wasn't run, and no e2e test signs in to `/admin`.
- Not checked against a real authenticator app or a real IdP. The RFC vectors cover TOTP; the
  first deploy should scan a QR code with Google Authenticator/1Password and run "test with my own
  e-mail" against a real Okta/Entra/Google tenant.
- No new dependencies.

## HANDOFF: continue at row 7 — frontend for rows 5 + 6 + sync audit — read `agent-orch/frontend_gaps_phase_A_to_D.md` first
