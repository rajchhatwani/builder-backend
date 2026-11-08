# Agent 7 report — claude-opus-5-5 — 2026-10-27

## Scope accepted
Queue row 7: frontend for rows 5 + 6 plus every item in `agent-orch/frontend_gaps_phase_A_to_D.md`
(P0-1 … P2-12). Frontend only; no backend changes.

I waited for agent 6 (session `builder-backend-17`) to tick row 6 and write its HANDOFF before
starting. Agent 6 then stopped its own row-7 attempt, and we agreed that I own row 7. The tree was not
touched by both of us at once.

Baseline before changes: `tests/api tests/unit` → **1916 passed, 2 skipped**.

## What was already done
- Backend for all of it: SSO (agent 5, `app/api/sso.py`), TOTP + org policies + SSO test/check (agent
  6, `app/api/account.py`, `app/api/orgs.py`, `app/api/admin.py`). See `agent_5.md`, `agent_6.md`.
- Frontend for phases A–C (agents 4 / 4b): org console, global 402/423 prompts, admin console.

## Decisions
- **QR code — added on the owner's request (follow-up, same day).** At first I shipped without one
  (no new dependency): just the key grouped in fours, with Copy, plus an `otpauth://` link. The owner
  then asked for it, so the setup step now shows a QR code first, then the key and the link as a
  fallback. **New dependency:** `qrcode@^1.5.4` (runtime) + `@types/qrcode@^1.5.6` (dev), in
  `frontend/package.json` / `package-lock.json`. It is loaded with a dynamic `import('qrcode')` in
  `TotpQr` (`components/MfaStep.tsx`), so it is its own ~23 kB chunk (9 kB gzip) and the main bundle
  doesn't grow. It renders an SVG `<img>` on a white tile (`.totp-qr`) so it scans in dark mode. If
  the chunk fails to load, the QR is simply hidden; the key and the link still work. Both places
  that use `TotpSecret` get it: staff enrolment at sign-in and Account → Two-factor.
- **One setup call per challenge.** Each `…/login/mfa/setup` call stores a *new* secret. React
  StrictMode (dev) runs the effect twice, so the key on screen could differ from the one the server
  kept, and the first code was refused. I found this while clicking through. `setupOnce()` caches
  the promise per `mfa_token`.
- **Email-first sign-in.** Email → Continue → `POST /account/login/discover` → either "Continue with
  <org> SSO" (a full navigation to `login_url`) or the password field. "Sign in with a password
  instead" stays available. If discovery fails, the password form still works (it's a convenience,
  not a gate). Sign-up is unchanged.
- **The Projects page doesn't trigger the 2FA prompt by itself.** Each project card loads its
  summary, so one org requiring MFA would pop the 403 prompt as soon as the page loaded. The page now
  reads `require_mfa` from `GET /orgs` and, only if some org has it, `session_mfa` from
  `GET /account/mfa`. Those orgs' projects render as "Needs 2FA" cards linking to Account, the same
  pattern as the locked-org cards.
- **Org console when the org's MFA policy blocks you.** `GET /orgs/{slug}` still works (by design), so
  the console shows the org name, a clear explanation, "Open your account" and **Leave** (also
  allowed), instead of an error page.
- **SSO tab is team-orgs only** (personal orgs answer 409); the tab is hidden for personal orgs.

## Implementation summary
- `frontend/src/api/types.ts`: types `MfaChallenge`, `LoginResult` + `isMfaChallenge()`,
  `TotpSetup`, `SessionWithRecoveryCodes`, `MfaStatus`, `OrgMfaDetail`, `OrgPolicies(+Update)`,
  `LoginDiscovery`, `SsoConfig`, `SsoConfigWrite`, `SsoDomain`, `SsoCheck`. New fields:
  `UserAccount.mfa_enabled`, `Organization.require_mfa / session_ttl_hours`,
  `OrgMember.mfa_enabled`, `AdminOrg.sso_* / require_mfa / session_ttl_hours`,
  `AdminOrgMember.mfa_enabled`. All checked against the live OpenAPI schema.
- `frontend/src/api/client.ts`:
  - `login` / `adminLogin` return `SessionResponse | MfaChallenge` and adopt the token only for a
    session.
  - `loginMfa` / `adminLoginMfa` = `{verify, setup, enable}`. These are sign-in style
    (`anonymous`), so a 401 never triggers refresh-and-retry.
  - `discoverLogin`; `mfaStatus`, `totpSetup`, `totpEnable` (adopts the new MFA'd token),
    `totpDisable`, `regenerateRecoveryCodes`.
  - `orgPolicies`, `updateOrgPolicies`; `ssoConfig`, `saveSsoConfig`, `deleteSsoConfig`,
    `activateSso`, `add/verify/removeSsoDomain`, `startSsoTest`, `checkSso`.
  - `adminResetMfa`, `adminCheckSso`; `adminAudit` accepts `actor_id` / `since`.
  - A global **403 `org_mfa_required`** listener (`onOrgMfaRequired`), next to the 402/423 ones.
- `frontend/src/api/ssoErrors.ts` (new): readable text for every `sso_error` reason and every
  `sso_test` result, with a generic fallback.
- `frontend/src/components/MfaStep.tsx` (new): the second sign-in step for both surfaces.
  - `TotpSecret`: QR code (`TotpQr`, lazy `qrcode`), key with Copy, otpauth link.
  - Verify: code or recovery code.
  - Enrol (staff): key + otpauth link → first code → recovery codes.
  - `RecoveryCodes`: shown once, Copy / Download, and "I saved them" must be ticked before Continue.
  - Errors: `invalid_mfa_code` stays on the step; `invalid_mfa_token` / `invalid_credentials` go back
    to the password form with a reason.
- `frontend/src/components/AuthProvider.tsx`: `signIn` resolves with the challenge or `null`;
  `completeSignIn(session)`.
- `frontend/src/pages/LoginPage.tsx`: email-first flow, SSO discovery, MFA step, `sso_error`
  message, and a message when `#/sso/complete` had no session to resume.
- `frontend/src/pages/admin/AdminApp.tsx`: admin sign-in with the MFA / enrolment step (**P0-1:
  the admin console signs in again**).
- `frontend/src/App.tsx`: `#/sso/complete` (the session is resumed from the cookie by
  `AuthProvider`, then it goes to `#/`); `ORG_TABS` gains `sso` and `policies`; `OrgMfaPrompt`
  mounted.
- `frontend/src/components/OrgMfaPrompt.tsx` (new): "<org> requires two-factor".
  - Without TOTP: "Turn on two-factor" → `#/account`.
  - With TOTP but a password-only session: "Sign out and sign in again".
- `frontend/src/components/TwoFactorSection.tsx` (new, on Account):
  - status;
  - turn on (password → key → code → codes; swaps in the new session);
  - new recovery codes;
  - turn off (password + code).
  - Turn off is hidden with an explanation when staff or an org requires 2FA; SSO-only accounts get
    a one-line note instead.
  - A warning appears when TOTP is on but this session didn't use it.
- `frontend/src/pages/OrgPoliciesTab.tsx` (new, `#/org/<slug>/policies`, "Security" tab):
  - require-MFA checkbox, with a confirm naming how many members will be blocked;
  - session length: platform default or custom 1–720 h;
  - sends only changed fields; `enable_mfa_first` is explained with a link to Account;
  - members see the values read-only plus "ask your admin".
- `frontend/src/pages/OrgSsoTab.tsx` (new, `#/org/<slug>/sso`):
  - status + last test;
  - Test with my own e-mail; Check configuration (checklist); Turn on/off (turning on without a
    passing test asks first; disabled without a verified domain); Remove configuration;
  - service-provider details with Copy;
  - domains: add → TXT record, Verify, Remove (readable 409s);
  - SAML/OIDC form: certificate summary with "blank keeps it", write-only client secret, JIT +
    role;
  - plan upgrade notice when `allowed_by_plan` is false;
  - the `?sso_test=` result banner.
  - `SsoChecklist` is reused by the admin console.
- `frontend/src/pages/OrgConsole.tsx`: SSO + Security tabs, People **2FA** column, MFA-blocked
  view. `AskAdmin` moved to `components/AskAdmin.tsx` so the new tabs share it.
- `frontend/src/pages/ProjectsPage.tsx`, `ProjectWorkspace.tsx`: "Needs 2FA" cards; the workspace
  explains a 403 `org_mfa_required` instead of "can't find this project".
- `frontend/src/pages/admin/AdminPages.tsx`:
  - People: **2FA** column + **Reset 2FA** (platform admins only, not yourself; reason required;
    danger dialog).
  - Organizations: **SSO** column ("SAML · on", "OIDC · off", "—"; last test in the tooltip).
  - Org detail: "Single sign-on and security" card with **Check SSO** (support may run it), the
    policies, and a members **2FA** column.
  - Audit: organization filter (also read from `#/admin/audit?organization_id=<uuid>`), a "Single
    sign-on" event group, and the `sso` source.
- `frontend/src/index.css`: `.status-err`, `.copy-row` (stacks at phone width), `.checklist`,
  `.plain-list`, `.recovery-codes`, `.field-note`, `.totp-qr`.
- `frontend/package.json` / `package-lock.json`: `qrcode` + `@types/qrcode` (see Decisions).

Gap items: P0-1 … P1-9, P2-10 and P2-12 done. **P2-11:** the UI shows raw action names and has no
label map, so there was nothing to extend. I added the `sso.` filter group instead.

## Tests / verification
The frontend has no unit-test setup (none existed, and adding one would mean a new dependency), so I
couldn't work red → green in the frontend. Instead I **clicked every flow in a real browser**:
headless Chrome (puppeteer-core) against a throwaway stack (Postgres in Docker, Alembic head
`f5c3a8e1b7d9`, uvicorn, Vite dev). TOTP codes came from `otplib`; the QR codes were decoded with
`jsqr`. The driver scripts and screenshots live in the session scratchpad, not the repo; those
test-only tools were not added to the repo (the only repo dependency is `qrcode`, above).

All **42 browser checks pass** (38 + 4 for the QR follow-up):
- **QR code:** on staff enrolment and on Account → Turn on, the QR decodes to exactly the
  `otpauth://` link, and a code made from the secret *read out of the QR* is accepted (so a phone
  scanning it works).
- **Admin sign-in:** staff enrolment; wrong code stays on the step; 10 recovery codes; Continue
  locked until "saved" is ticked; signed in; the second sign-in asks for a code only.
- **Account two-factor:** wrong password gives a 422 message and the session stays; turn on → codes
  → "10 left".
- **Customer sign-in:** email → password → code.
- **Org console:** People 2FA column. Security tab: members-without-2FA count, confirm, saved
  (checked in the DB).
- **SSO tab:**
  - add domain → TXT record; verify without DNS → readable 409;
  - SAML save → certificate summary; checklist; Turn on disabled without a verified domain;
  - after verifying via SQL: Turn on with confirm → "SAML · on";
  - `?sso_test=email_mismatch` text.
- **Login page:** discovery shows "Continue with Acme SSO"; `sso_error=not_provisioned` and unknown
  reasons explained.
- **Member without 2FA:** "Needs 2FA" card; 403 prompt in the workspace; the org console explains;
  Account lists the org.
- **Org policy on Alice:** Turn off is hidden while an org requires 2FA.
- **Admin console:** orgs "SAML · on"; detail policies + Check SSO checklist; audit org filter from
  the URL; Reset 2FA clears TOTP (checked in the DB).

**Only type-checked, not clicked:**
- the real IdP round trip (`#/sso/complete` after a real SAML/OIDC login, and the "Test with my own
  e-mail" redirect), which needs a real IdP;
- the OIDC form;
- "New recovery codes" and "Turn off" on Account;
- `enable_mfa_first`;
- Remove configuration / Remove domain;
- the "sign out and sign in again" button in `OrgMfaPrompt`;
- phone-width layout.

## Test run result
- `uv run pytest tests/api tests/unit -q` → **1916 passed, 2 skipped** (no backend changes; same as the baseline).
- `npx tsc -b` clean; `npx vite build` OK (the existing >500 kB chunk warning; `qrcode` is a
  separate 23 kB chunk); `npm run lint` → **57 warnings, 0 errors, unchanged**, none in new files.

## Improvement scope — out of current phase
- The `?sso_test=` / `?sso_error=` banners read the hash when the page loads, which is what a real
  IdP redirect does. A same-page hash change to those URLs wouldn't refresh them. That's harmless
  today, because nothing in the app links there.
- The frontend has no test runner. A small Vitest + Testing Library setup would let future frontend
  rows work test-first. It's a new dev dependency, so it's the owner's call.
- `GET /projects` could flag MFA-blocked orgs the way it flags locked ones; the Projects page would
  then not need `GET /account/mfa` (agent 6 noted the same).
- The admin audit organization filter takes a UUID; an org picker would be friendlier.

## Open items / known issues
- Not checked against a real authenticator app or a real IdP (same as agent 6). The first deploy
  should scan/enter the key in Google Authenticator / 1Password and run "Test with my own e-mail"
  against a real Okta/Entra/Google tenant.
- One new dependency: `qrcode` (+ `@types/qrcode`), added at the owner's request.
- The QR code was decoded by a library in a browser, not scanned by a real phone camera. The first
  deploy should scan it once with a real authenticator app.

## Notes for agent 8 (row 8 — Phase E SCIM 2.0)
Scope is plan §4.3 + §12.E: `scim_directories` migration; `/scim/v2` Users, Groups,
ServiceProviderConfig, ResourceTypes, Schemas; group → role mapping; bearer rotation; the customer
setup UI; operator status. What already exists for you to build on:

**Backend**
- `plans.allow_scim` already exists (`app/models/platform.py` `Plan`), and is exposed in
  `schemas/account.py` and `schemas/organization.py`. Gate on it the way SSO gates on `allow_sso`:
  `SsoService.allowed_by_plan()` plus the usual 402 `quota.denied` (`app/services/sso_service.py`).
- Bearer token: store only a hash. Use `hash_token()` (`app/core/platform_security.py`); `ApiToken` /
  `RefreshToken` / invitations already use the `token_hash String(64)` pattern. Show it once, like
  recovery codes. Never log it (trigger-file rule).
- Deactivation (`active: false`) per §4.3 means removing this org's membership, clearing sessions
  and bumping `PlatformUser.token_version` (it's a JWT claim `tv`, so that kills PATs and access
  tokens). `PlatformAuthService.revoke_all_sessions(user)` (`app/services/platform_auth_service.py`,
  also used by `mfa_service.py`) does the refresh-token + `token_version` part. Note: that signs
  the user out **everywhere**. §4.3 says only this org's access dies and personal orgs stay, so
  removing the membership is the real cut. Decide (or ask the owner) whether a global sign-out is
  acceptable, and how to handle `ApiToken`s scoped to this org's projects
  (`api_token_service.revoke_for_project`).
- JIT from SSO only provisions at login (agent 5); SCIM is the offboarding path, so SSO and SCIM
  stay independent tables (§2 `ScimDirectory`).
- Audit actions should be `scim.*`. The admin audit filter has an action-group `<select>`
  (`AdminPages.tsx`, the `sso.` option); add `scim.` there.
- Seats (§6): SCIM user create counts against seats like invite accept does.

**Frontend (if row 8 includes the UI; the row says "setup UI, operator status")**
- Plan §5 puts SCIM on the same page as SSO (`#/org/<slug>/sso` = "SSO & SCIM"). Add a SCIM section
  to `frontend/src/pages/OrgSsoTab.tsx` rather than a new tab. Reuse:
  - `Copyable` in the same file, for the base URL `…/scim/v2` and the token;
  - `RecoveryCodes`-style show-once + "I saved it" gate (`components/MfaStep.tsx`), for the bearer;
  - the `allowed_by_plan` upgrade notice and `AskAdmin`, for members;
  - `useUi().confirm` for "Rotate token" (the old token stops working at once).
- Operator status: the admin org list has an SSO column (`SsoStatus` in `AdminPages.tsx`) and the
  org detail has a "Single sign-on and security" card. Put the SCIM status/rotation there.
- Types go in `api/types.ts`, calls in `api/client.ts`; check them against the live OpenAPI.
- New dependencies: `qrcode` is now in the frontend; anything else must be noted (trigger rule).

**How to click through it:** there's no frontend test runner. I used puppeteer-core against a
throwaway stack: `docker run --rm --name … -p 55432:5432 postgres:16-alpine`, `alembic upgrade
head`, uvicorn with a local env file (`BUILDER_ENVIRONMENT=local`, CORS for `:5173`,
`BUILDER_SIGNUP_MODE=open`, a bootstrap admin, `BUILDER_AUTH_RATE_LIMIT_ATTEMPTS=1000` so
repeated sign-ins don't hit 429), and `npx vite`. The admin must enrol TOTP on first sign-in, so
keep the secret to make codes. SCIM itself can be driven with plain `curl` and the bearer.

## HANDOFF: continue at row 8 — Phase E SCIM 2.0 — read `agent_6.md` and this report first
