# Frontend gaps after Phases A–D (backend done) — for queue row 7

Written by agent 6 (2026-10-27) after comparing every backend route in the OpenAPI schema with the
paths `frontend/src/api/client.ts` calls. Phases A–C are fully wired (every route is used). Everything
below is backend that exists and is tested but has **no UI yet**, or UI that the backend changed
under it. **No backend changes are needed for any item**; if you find one that does, write it in
your report instead of changing the backend.

Endpoint details: docstrings at the top of `app/api/sso.py`, `app/api/orgs.py`, and the
`/account/mfa*` + `/account/login/mfa*` handlers in `app/api/account.py`; schemas in
`app/schemas/account.py`, `app/schemas/organization.py`, `app/schemas/sso.py`. The live OpenAPI
schema (`/openapi.json`) is the contract — check field names against it.

Priority: **P0** = something visibly broken today; **P1** = plan feature with no UI; **P2** = polish.

---

## P0 — sign-in now has a second step (breaks today's UI)

### 1. Admin console sign-in (`pages/admin/AdminApp.tsx`, `api/client.ts` admin login)
`POST /admin/login` **no longer returns a session for staff**. Platform staff always need TOTP
(§4.4), so a correct password answers `200`:

```json
{ "mfa_required": true, "enrollment_required": true|false, "mfa_token": "…", "expires_in": 300,
  "methods": ["totp"] | ["totp", "recovery_code"] }
```

- `enrollment_required: false` → show a "6-digit code (or a recovery code)" field →
  `POST /admin/login/mfa {mfa_token, code}` → `SessionRead` (cookie set, same as the old login).
- `enrollment_required: true` (first sign-in of a staff account) →
  `POST /admin/login/mfa/setup {mfa_token}` → `{secret, otpauth_uri}`: show a **QR code** of
  `otpauth_uri` (new dependency needed, e.g. `qrcode` — note it in your report; or show the secret
  for manual entry if you'd rather not add one) plus the secret as text → user types the first code →
  `POST /admin/login/mfa/enable {mfa_token, code}` → `SessionRead` **plus `recovery_codes` (10)**:
  show them once with copy/download and an "I saved them" confirm before continuing.
- Errors: `401 invalid_mfa_code` (wrong code — stay on the step), `401 invalid_mfa_token` (the
  5-minute step expired — back to the password form), `401 invalid_credentials` (locked).
- These calls are sign-in style: a 401 must **not** trigger the refresh-and-retry path in
  `client.ts` (use the same `anonymous` option the login call uses).
- Until this ships, local dev can set `BUILDER_ADMIN_MFA_REQUIRED=false`.

### 2. Customer sign-in (`pages/LoginPage.tsx`)
`POST /account/login` returns **either** `SessionRead` **or** the same `MfaChallengeRead` shape
(when the account has TOTP on, or for staff using the customer app). Detect `mfa_required`.
- `POST /account/login/mfa {mfa_token, code}` → session.
- Staff enrolment variant: `POST /account/login/mfa/setup` / `…/enable` (same as admin).
- `/account/register` is unchanged (new accounts have no MFA).

### 3. SSO sign-in on the login page (§4.2 step 1)
- Email first: `POST /account/login/discover {email}` → `{method: "sso", login_url,
  organization_name}` → show "Continue with <organization_name> SSO" and set
  `window.location.href = login_url` (a full navigation, not fetch); `{method: "password"}` → show
  the password field.
- New route **`#/sso/complete`**: the API redirects here after a successful SSO sign-in with the
  refresh cookie already set. Call the existing session-resume (`/account/refresh`) and go to the
  projects page.
- **`#/login?sso_error=<reason>`**: show a readable message. Reasons: `sso_unavailable`,
  `email_domain_not_verified`, `not_provisioned` (JIT off — "ask your admin to invite you"),
  `seat_limit`, `account_suspended`, `staff_account`, `invalid_request_state` ("start again"),
  `bad_signature`, `idp_error`, `malformed`, `discovery_failed`, `jwks_failed`, `insecure_url`,
  `invalid_test_ticket`; anything else → generic "SSO sign-in failed (<reason>)".

---

## P1 — plan features with no UI

### 4. Account → Two-factor authentication (`pages/AccountPage.tsx`) — §4.4
- `GET /account/mfa` → `{totp_enabled, enabled_at, recovery_codes_left, session_mfa,
  required_for_staff, required_by: [{organization_id, slug, name}], sso_only}`.
- Turn on: `POST /account/mfa/totp/setup {password}` → `{secret, otpauth_uri}` (QR + secret) →
  `POST /account/mfa/totp/enable {code}` → **a new `SessionRead` + `recovery_codes`**: replace the
  in-memory access token with the returned one (it counts as MFA'd), show the codes once.
- Turn off: `POST /account/mfa/totp/disable {password, code}` → 204. Hide/disable the button and
  explain when `required_for_staff` or `required_by` is non-empty (the API answers 409
  `mfa_required_for_staff` / `mfa_required_by_org` with the orgs in `details`).
- New recovery codes: `POST /account/mfa/recovery-codes {code}` → `{recovery_codes}`.
- `sso_only: true` → no TOTP section; say "your organization's SSO handles two-factor".
- Errors here are **422** (`invalid_password`, `invalid_mfa_code`), never 401, so the session stays.
- `UserRead.mfa_enabled` is now on `/account/me`.

### 5. Org MFA policy blocks (§4.4, §12.D.7) — global handler next to 402/423 in `api/client.ts`
Any org route or project route of an org with "require MFA" answers **403 `org_mfa_required`**
for a session without a second factor, `details[0] = {organization_id, organization_slug,
organization_name, mfa_enabled}`. Show a prompt (like `OrgLockedPrompt`):
- `mfa_enabled: false` → "<org> requires two-factor authentication" + link to `#/account` (turn it on).
- `mfa_enabled: true` → "sign in again with your code" + a sign-out-and-back-in button (the current
  session was started with password only).
`GET /orgs/{slug}` and leaving the org still work, so the org console shell can render the message.
`OrganizationRead` now has `require_mfa` and `session_ttl_hours`.

### 6. Org console → Security policies tab `#/org/<slug>/policies` (§8, §8.1) — admins
- `GET /orgs/{slug}/policies` → `{require_mfa, session_ttl_hours, members_without_mfa,
  default_session_hours}`; `PATCH /orgs/{slug}/policies {require_mfa?, session_ttl_hours?}` (send
  only changed fields; `session_ttl_hours: null` = platform default; 1–720).
- Turning MFA on: the API answers **409 `enable_mfa_first`** unless the admin's own session used
  MFA — explain and link to `#/account`. Warn with `members_without_mfa` ("N members will be
  blocked until they turn on 2FA").
- Members get the existing "ask your admin" 403 (`org_role_required`).
- "Allow operator impersonation" is in §8 too but belongs to row 9 (Phase F) — leave it out.

### 7. Org console → SSO tab `#/org/<slug>/sso` (§8, §12.D.6) — admins, team orgs only
All under `/orgs/{slug}/sso` (session only; API tokens get 403 `session_required`):
- `GET` → `SsoConfigRead`: `configured, allowed_by_plan, protocol, active, idp_*,
  idp_certificate {sha256_fingerprint, not_after, subject}, oidc_*, oidc_client_secret_set,
  jit_enabled, jit_role, last_test {at, result, tested_by_email}, sp {entity_id, acs_url,
  metadata_url, oidc_redirect_uri, login_url}, domains[]`.
- `allowed_by_plan: false` → upgrade prompt linking to the Plan tab (saving answers 402
  `sso_not_in_plan`, which the existing QuotaPrompt also handles). Personal orgs: hide the tab (409
  `sso_not_for_personal_orgs`).
- **Service-provider details** to copy into the IdP: entity ID, ACS URL, metadata URL (SAML);
  redirect URI (OIDC). Copy buttons.
- **Domains**: `POST …/sso/domains {domain}` → shows `dns_record_type/name/value` (the TXT record to
  add); `POST …/sso/domains/{domain}/verify` (409 `domain_not_verified` while DNS isn't there yet —
  show the record again); `DELETE …/sso/domains/{domain}`. Errors: `domain_taken`,
  `public_email_domain`, `invalid_domain`, `last_verified_domain`.
- **Config form**: `PUT …/sso` with `protocol` = `saml` (`idp_entity_id`, `idp_sso_url`,
  `idp_cert_pem` textarea) or `oidc` (`oidc_discovery_url`, `oidc_client_id`,
  `oidc_client_secret` — write-only; show "set" when `oidc_client_secret_set`, blank = keep), plus
  `jit_enabled` and `jit_role` (member|admin). Errors: `invalid_certificate`, `insecure_url`,
  `invalid_url`, `oidc_client_secret_required`, `invalid_sso_config`. `DELETE …/sso` removes it.
- **Test with my own e-mail**: `POST …/sso/test` → `{login_url, expires_in}` →
  `window.location.href = login_url`. The IdP round trip comes back to
  **`#/org/<slug>/sso?sso_test=<result>`** without changing the session: show `ok` as success, else
  the reason (`email_mismatch` = "you signed in to the IdP as someone else",
  `email_domain_not_verified`, plus the `sso_error` reasons above). Works before activation.
- **Check**: `POST …/sso/check` → `{ok, protocol, active, checks: [{name, status: ok|warning|error,
  detail}]}` — render as a checklist (plan, verified_domain, configuration, active, certificate,
  client_secret, discovery, jwks, last_test).
- **Activate / deactivate**: `POST …/sso/activate|deactivate` (409 `no_verified_domain`,
  `sso_not_configured`). Suggest testing first when `last_test.result !== "ok"`.

### 8. Org console → People: 2FA column (§8)
`OrganizationMemberRead.mfa_enabled` — show "2FA on/off" next to last sign-in.

### 9. Admin console — SSO status + test button (§7, §12.D.5), MFA reset
- Organizations list + org detail: `AdminOrgRead` now has `sso_protocol` (null = none),
  `sso_active`, `sso_verified_domains`, `sso_last_test_at`, `sso_last_test_result`,
  `require_mfa`, `session_ttl_hours`. Add an "SSO" column (e.g. "SAML · on", "OIDC · off", "—").
- Org detail: **Check SSO** button → `POST /admin/organizations/{id}/sso/check` (same
  `SsoCheckRead` checklist). Support staff may run it.
- Org detail members: `AdminOrgMemberRead.mfa_enabled` column.
- User detail: **Reset two-factor** (platform admin only, danger confirm with a reason) →
  `POST /admin/users/{id}/reset-mfa {reason}` → `AdminUserRead`; 409 `cannot_reset_own_mfa`.
  Signs the person out everywhere. Show `mfa_enabled` on the user detail/list too (`AdminUserRead`
  inherits it from `UserRead`).

---

## P2 — smaller gaps found in the sync audit

10. **Admin Audit tab filters** (`AdminPages.tsx` ~line 1468): the API also filters by
    `organization_id`, `actor_id`, `project_id` and `since` (§7 "new filter: organization_id"); the
    UI only sends `action`, `result`, `via`. Add at least an organization filter. `via` values now
    include `sso`.
11. **New audit actions** to label nicely if the UI maps action names: `account.mfa_challenge`,
    `account.mfa_enabled`, `account.mfa_disabled`, `account.mfa_recovery_codes_regenerated`,
    `admin.user_mfa_reset`, `org.policy_changed`, `admin.sso_checked`, and `sso.login`,
    `sso.login_failed`, `sso.jit_provisioned`, `sso.test`, `sso.test_started`, `sso.config_updated`,
    `sso.activated`, `sso.deactivated`, `sso.deleted`, `sso.domain_added`, `sso.domain_verified`,
    `sso.domain_removed`.
12. **Org route table** `App.tsx` `ORG_TABS` = people, invites, projects, plan, audit → add `sso`
    and `policies` (§8.1).

## Gate
`npx tsc -b`, `npm run lint` (no new warnings — 57 existing), `npx vite build`; backend suite stays
green (`uv run pytest tests/api tests/unit -q`). Check the flows in a browser against the dev
stack where you can (agent 4b noted its screens were contract-checked but **not clicked
through**); say plainly in your report what you clicked and what you only type-checked.
