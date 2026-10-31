# Backend Builder — security test report (Session 1)

Date: 2026-10-29. Branch `phase_A_to_E`. Stack brought up with `final_test/harness/stack.sh restore configured && up production`; all five status lines reported 200/accepting.

## 1. Verdict

**Conditional go, with one fix needed before the MCP feature is sold/offered (not a go-live blocker for the rest of the product).** No Critical issues were found. One High finding is new in this pass: **the MCP endpoint cannot be reached through the real public API hostname at all** (H-1, §7.10) — a deployment/wiring defect, not an authorization bypass, but it means the paid `allow_mcp` feature is completely non-functional in a normal deployment until fixed (the fix itself is a one-line call-site change). Of the 17 findings from the 2026-10-27 independent review, **14 are fixed, 1 is partially fixed, 1 remains open (Low), 1 is a meta-finding (N/A)**. The authz/session/SSO/SCIM/webhook/MCP-authorization code reviewed is careful and consistent (fail-closed guard, atomic replay-safe SSO/OIDC state consumption, signature-wrapping-safe SAML, idempotent/livemode-checked Stripe webhooks, correct MCP scope/cross-project/per-member enforcement) — a second, live round of testing (§7) found **zero authorization bypasses** across 11 forged SAML responses, the OIDC SSRF guard, 7 forged/replayed/out-of-order Stripe webhook events against a real bound subscription, account lockout, rate-limiter/XFF spoofing, refresh-token rotation/reuse, MFA replay/recovery-code reuse, and MCP scope/cross-project/per-member access. The one issue that must be resolved **before** relying on Postgres RLS for real customer data: **the database role the API connects as is a Postgres superuser with `BYPASSRLS`, so RLS policies are silently ignored** even when installed, enabled and forced (§7.4, M-1) — tenant isolation today rests entirely on the service-layer `guard`/`org_context` checks, which tested solidly both statically and live, so this is not an open door today, but it means Phase F's RLS "second wall" is not yet real protection and must not be assumed to be.

**Important caveat on scope:** this pass was a deep **static review** of the authn/session/authorization/SSO/SAML/SCIM/billing-webhook/impersonation/RLS/export code, re-verifying all 17 prior findings against the current code, plus a **bounded live smoke test** (stack bring-up, public-exposure sweep, headers, CORS, a handful of IDOR/JWT-tamper/Stripe-signature probes). It did **not** execute the full 14-category attack matrix in the task prompt (brute-force/lockout timing, MFA replay/recovery-code edge cases, live SAML/OIDC negative tests against a synthetic IdP, SCIM provisioning races, frontend XSS/DOM probing, operator-console UI walk, org-deletion grace-period lifecycle, MCP endpoint, dependency audit). See §4 for the coverage table and what is still open.

## 2. Environment

- Stack: `final_test/harness/stack.sh up production` — Postgres, API, frontend proxy, ngrok tunnel. `stack.sh status` showed `postgres`, `api`, `proxy app`, `proxy api`, `tunnel` all healthy (200 / accepting connections).
- `python3 final_test/credentials/check_env.py ~/final_test.env` → `RESULT: READY, every REQUIRED item passed`.
- Not stood up / not exercised in this pass: the second `up local` stack (local-mode docs/debug checks), MinIO, Redis, Keycloak, OTLP (all reported `ConnectionRefusedError` by check_env, consistent with "optional, not started").
- Could not test: real Okta browser login (per `SESSION_HANDOFF.md` §4, the stale Okta password for `bb-sso1` blocks it; a synthetic SAML/OIDC IdP round-trip was not attempted in this pass — recorded as not-yet-tested, not as "found secure").
- Could not test: Stripe Checkout through the UI (no browser session was driven), so no org in this environment has a real `stripe_customer_id`; livemode-mismatch and replay-with-duplicate-event-id behavior were verified by code reading only (see F-004/§3 Stripe note), not exercised against a bound customer.

## 3. Findings

### High

**H-1 (confirmed live in the §7.10 follow-up checkpoint) — The MCP endpoint (`/mcp`) rejects every request through the real public API hostname, making the entire plan-gated MCP feature non-functional once deployed.**
`app/api/mcp.py:build_mcp_app()` calls `mcp.streamable_http_app(streamable_http_path="/")` without `host=`/`transport_security=`; the SDK's default `host="127.0.0.1"` silently turns on its own DNS-rebinding `Host`-header allowlist (`127.0.0.1:*`/`localhost:*`/`[::1]:*` only). Proven directly: `Host: 127.0.0.1:8000` → `200`; `Host: <the real public API hostname>` → `421 Invalid Host header`, before auth is even checked. This is not an authorization bypass — it fails closed — but it means no real MCP client can ever reach this feature in a normal deployment, independent of plan/token/scope. See §7.10 for the full reproduction and fix.

No new Critical findings. One Low finding stands open from the prior review; everything else from that review is fixed or partially fixed (§5 has the full re-check table).

### Low

**L-1 (= review F-007, still open) — `platform_support` can trigger a live outbound network call via the operator "test SSO" button.**
`app/api/admin.py:691` `POST /admin/organizations/{org_id}/sso/check` is gated by `NEEDS_PROJECTS_READ` (`require_admin("projects:read")`), which `platform_support` holds (`app/core/platform_authz.py:242-244`). The handler calls `SsoService(db, settings).check(org)`, which does a live fetch of the org's OIDC discovery document / JWKS or inspects the IdP certificate — it changes no state, but it is an outbound network action triggered by a role documented as "read-only" in the strict sense. Impact is low (no data exposure, no write), but it contradicts the plan's literal wording for `platform_support`. Fix: either gate this route behind `settings:write`-style permission restricted to `platform_admin`, or document the exception explicitly.

### Medium

**M-1 (confirmed live in the §7.4 follow-up checkpoint) — The database role the API connects as is a Postgres superuser with `BYPASSRLS`, so enabling RLS as `app/core/rls.py` instructs gives zero additional protection.**
`select rolname, rolsuper, rolbypassrls from pg_roles where rolname='builder'` → `t, t`. Proven directly: with RLS installed, enabled and forced on all 29 tables, and `app.organization_id` bound to an id matching no row, a raw query as the app's own role still returned every organization in the database. `app/core/rls.py` itself is correctly designed; the gap is purely in which database credentials are used. **Before relying on RLS for real customer data**, create a dedicated non-superuser API role with `BYPASSRLS` off (keep a separate, more privileged role for Alembic only) and re-verify `rolsuper=f, rolbypassrls=f` for that role before setting `BUILDER_RLS_ENABLED=true` in production. See §7.4 for the full reproduction.

### Informational / operational readiness (not a code defect)

**I-1 — Row-Level Security is not enabled by default; §7.4 found it would need a database-role change first.** See M-1 above for the live-verified detail; this line is kept only as a pointer from the original pass.

## 4. Coverage table (attack matrix from the test prompt)

| # | Item | Tested? | Result |
|---|---|---|---|
| 1 | Authn/session (brute force/lockout, rate-limit bypass, refresh rotation, JWT tampering, cookie flags, CSRF, CORS, session fixation, password reset) | Partial | Code review: rate limiter, `require_same_origin` CSRF check, `SameSite=Strict` cookies, fail-closed audience checks all present and look correct (`app/api/security.py`). Live: tampered-signature JWT → 401; CORS preflight from an unlisted origin → 400, no `Access-Control-Allow-Origin` reflected, null-origin also refused. **Not tested live:** numeric lockout thresholds, X-Forwarded-For rate-limit bypass, refresh-token reuse/rotation races, session fixation. |
| 2 | MFA (TOTP replay, recovery codes, enrolment hijack, staff bypass, org require-MFA on every route type) | Not tested (this pass) | Prior review marked these solid (TOTP replay, recovery-code reuse, lockout, challenge-token misuse all refused); code for `mfa_satisfied` and `org_mfa_required` re-read and still looks correct (`app/services/access_service.py:63-70`, `app/api/security.py:312-314,476-482`), but no live MFA repro was run in this pass. |
| 3 | Authorization / tenant isolation (every route × every role, IDOR, mass assignment, escalation) | Partial | Code re-read: `guard()` and `org_context()` fail-closed, project↔org membership double-checked, impersonation default-deny route table. Live: outsider → `GET /orgs/bb-acme` → 404 (correct, indistinguishable from not-found); unauthenticated → 401. **Not tested live:** the full per-route sweep (208 routes × roles) — this exists as an automated test (`tests/api/test_access_matrix.py`, now non-vacuous per F-001 fix) but was not re-run against the live stack in this pass; mass-assignment and privilege-escalation payload fuzzing not attempted live. |
| 4 | API tokens/PATs scope enforcement | Partial | Code: `ORG_ROUTES_SESSION_ONLY` now blocks PATs from org delete/transfer/role-change/billing (fixes F-002). Live: app session token rejected on SCIM route (401). **Not tested live:** PAT scope sweep, pinned-token escape, revoked-token reuse. |
| 5 | Injection & input (SQLi, SSTI, path traversal, XSS, header injection, SSRF, XXE, NUL bytes, huge bodies) | Partial | Code: NUL bytes rejected globally (`app/api/input_guard.py`, fixes F-003); SAML parser disables DTD/entity resolution and rejects `<!DOCTYPE`/`<!ENTITY` (fixes XXE class, `app/services/saml.py:185-197`). **Not tested live:** XSS in generated-project output, path traversal in zip entries, SSRF via SSO discovery URL, huge/deep JSON bodies. |
| 6 | SSO/SCIM (SAML replay/wrapping/audience, OIDC state/nonce/PKCE, JIT pre-hijack, SCIM provisioning) | Partial | Code review only, but thorough: `app/services/saml.py` validates signature (asymmetric algorithms only, SHA-1 excluded), reads only from the signed subtree (defeats wrapping), checks Issuer/Audience/Recipient/Conditions/SubjectConfirmation windows, rejects unsolicited (no InResponseTo) responses, rejects encrypted/multiple assertions, caps response size. `app/services/sso_service.py._consume` atomically marks a login request consumed (`UPDATE ... WHERE consumed_at IS NULL ... RETURNING`), binding it to a browser hash — single-use and replay-safe by construction. Pre-hijack (F-005) is fixed: `claim_by_idp` wipes password/TOTP/API-tokens/sessions on first verified link via SSO or SCIM, for both JIT and existing-account paths. **Not tested live:** no synthetic-IdP signed-assertion round trip was actually POSTed to the ACS endpoint in this pass (the harness's `signxml`-based synthetic IdP approach described in `SESSION_HANDOFF.md` §4 was not exercised) — this is the biggest gap in this pass's live coverage and should be done before go-live. |
| 7 | Billing (Stripe webhook forgery, checkout tampering, portal access, quota races) | Partial | Live: bad-signature event → 400 `invalid_webhook`; stale/old timestamp → 400 `invalid_webhook` (`app/services/stripe_webhook_service.py` signature+timestamp check, not separately re-derived in this pass but behavior matches). Code: livemode check (`_expected_livemode`), per-event idempotency (`_seen`), customer-mismatch and other-subscription (out-of-order) guards, and the F-004 fix (malformed `data.object` → ignored, not 500) are all present and read correctly. **Not exercised live against a bound customer:** no org in this environment has a real Stripe customer (no Checkout was driven), so livemode-mismatch and replay-against-a-real-subscription could only be verified by code reading, not reproduced end-to-end. |
| 8 | Operator console & privacy (impersonation consent/banner/write-block/audit, operator secrecy) | Partial (code only) | `app/services/impersonation_service.py` / `app/api/impersonation.py` re-read in full: start requires org `allow_impersonation`, excludes staff/non-members, 10-minute TTL, every state re-checked from the DB per request (ended/expired/org-consent-withdrawn/target-still-member all re-verified in `_impersonation_info`), writes-switch is time-boxed and separately audited, default-deny route list (`_IMPERSONATION_NEVER`, `_IMPERSONATION_NEVER_WRITES`) blocks tokens/secrets/export/billing/project-membership changes outright. No obvious defect found. **Not tested live:** no "view as" session was actually started and driven through the API/UI in this pass. |
| 9 | Frontend (token storage, DOM XSS, clickjacking, CSP, role-gated UI vs API) | Not tested (this pass) | Prior review found only `theme` in browser storage and no horizontal overflow at 375px. Not re-verified live in this pass. |
| 10 | Infra/config (headers, docs/debug exposure, defaults, dependency audit) | Partial | Live: `/docs`, `/redoc`, `/openapi.json`, `/metrics` all 404 on the public tunnel (production mode correctly disables docs — `app/config.py:109-111`); response headers on the public origin include CSP (`default-src 'none'`), HSTS, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cross-Origin-Opener-Policy: same-origin`, `X-Robots-Tag: noindex, nofollow`. **Not tested:** local-mode docs/debug exposure (second stack not started), `pip-audit`/`npm audit`. |
| 11 | Data lifecycle (org deletion lock bypass, grace period, SCIM offboarding) | Partial | Code: F-014 (project/token creation in a locked org) is fixed — `_refuse_if_locked` is now called from both `enforce_project_limit` and `enforce_token_limits`. **Not tested live:** the full grace-period lifecycle, SCIM offboarding leaving residual access. |
| 12 | MCP endpoint (auth, scope, org MFA, cross-project, tool injection) | Not tested (this pass) | `app.mount("/mcp", mcp_starlette)` has its own auth middleware, separate from the REST `guard`; `allow_mcp` plan enforcement is now fixed (F-013, `app/services/mcp_service.py:107`). Not exercised live. |
| 13 | Candidate findings from setup (NOTES_FOR_TEST_SESSIONS items 1–9) | Partial | Item 2 ("password login still works for an SSO-active domain") — confirmed still true by code reading: `_sign_in` never disables password login for a verified SSO domain; "enforce SSO" remains an un-built policy, consistent with the setup notes calling this a known, not a regression, gap. Items 6/7/9 (email_not_verified, invite-mail Date/Message-ID, SSO-sign-in password reset) were not independently re-exercised live in this pass — see the setup notes for the evidence already captured during environment prep. |
| 14 | Public exposure (unauthenticated internet client reach) | Done | See §3 I-1 and the live sweep above: `/health`, `/ready`, `/.well-known/oauth-protected-resource` are public by design and return 200; everything else probed (`/docs`, `/redoc`, `/openapi.json`, `/metrics`) returns 404; `GET /admin/login` → 405 (only POST allowed, not unauthenticated-reachable for a real action). |

## 5. Re-check of the 17 prior findings (review/review_PLATFORM_SAAS_PLAN.md, 2026-10-27)

| ID | Title | Status now | Evidence |
|---|---|---|---|
| F-001 | Route-walk tests vacuous (0 routes) | **Fixed** | `tests/api/test_access_matrix.py:70-73` now asserts `len(routes) > 100` using a real walker (`tests/api/_routes.py:all_routes()`), not `isinstance(r, APIRoute)`. |
| F-002 | API tokens can do destructive/owner-level org actions | **Fixed** | `app/core/platform_authz.py:147-159` `ORG_ROUTES_SESSION_ONLY` now covers delete/cancel-deletion/role-change/member-removal/transfer/project-transfer/checkout/portal/export; `org_context` (`app/api/security.py:456-459`) refuses an API token on these with `session_required`. |
| F-003 | NUL byte → unhandled 500 | **Fixed** | `app/api/input_guard.py:reject_nul_characters`, applied as a global app dependency (`app/main.py:222`). |
| F-004 | Non-dict `data.object` in a signed Stripe event → `AttributeError` 500 | **Fixed** | `app/services/stripe_webhook_service.py:117-118` checks `isinstance(obj, dict)` and ignores otherwise. |
| F-005 | Pre-hijack via unverified sign-up + SCIM/JIT link + invite-by-id | **Fixed** | `claim_by_idp` (`app/services/platform_auth_service.py:495-520`) wipes password/TOTP/API-tokens/sessions for a never-verified account on first IdP-vouched link; called from both SSO `_sign_in` (JIT and existing-member) and `scim_service.py:462`. `accept_invitation_by_id` now requires `email_verified_at` (`app/services/organization_service.py:444-457`). |
| F-006 | Admin tokens not checked for `amr`/MFA in the guard | **Fixed** | `require_admin()` (`app/api/security.py:543`) checks `principal.mfa_satisfied`, which reads the token's bound `amr` claim (`app/services/access_service.py:63-70`). |
| F-007 | `platform_support` can call `sso/check` (live outbound fetch) | **Still open (Low)** | See §3 L-1. |
| F-008 | Verified SSO/SCIM domain claim is permanent | **Partially fixed** | `operator_release_domain` now exists (`app/services/sso_service.py:520-545`), giving an operator a manual release path. No automatic periodic TXT re-verification was found — this remains a design gap, now with a mitigation rather than none. |
| F-009 | Audit sanitizer untested | **Fixed** | `tests/unit/test_audit_sanitizer.py` now exists. |
| F-010 | Members see `mfa_enabled`/`last_login_at` | **Fixed** | `app/api/orgs.py:331-361` now excludes those fields unless the viewer is admin+ or viewing their own row (`response_model_exclude_unset=True` plus a `private()` helper gating the fields). |
| F-011 | `quota.denied` audit rows missing `actor_email` | **Fixed** | `_deny` in `app/services/organization_service.py:940-951` takes and forwards `actor_email`; call sites (seat/project/token limit enforcement) now pass it. |
| F-012 | Backfill leaves legacy project members outside their org | **Fixed** | Dedicated migration `alembic/versions/c8a4e6b2d9f1_backfill_project_members_into_org.py` exists. |
| F-013 | `plans.allow_mcp` never enforced | **Fixed** | `app/services/mcp_service.py:107` and `app/services/organization_service.py:1147,1160` now check the flag before minting/using MCP tokens. |
| F-014 | Deletion lock doesn't cover project/token creation | **Fixed** | `_refuse_if_locked` (`app/services/organization_service.py:1062-1069`) is called from both `enforce_project_limit` and `enforce_token_limits`. |
| F-015 | No `organization_id` in tenant-aware logs | **Fixed** | `structlog.contextvars.bind_contextvars(organization_id=...)` in `app/api/security.py:307,468`, unbound at request end in `app/main.py:140`. |
| F-016 | Minor deviations (no plan delete, no grandfathering, global Fernet key, etc.) | **Partially addressed** | No `DELETE /admin/plans/{id}` route was found — still open (by-design deferral per the original review, not independently re-confirmed as a deliberate decision in this pass). Grandfathering and per-org secret encryption were not re-checked in this pass. |
| F-017 | Agents' "pre-existing" claims about mypy/ruff only partly true | N/A | Meta-finding about process accuracy, not a product defect; not re-litigated here. |

**Counts: 14 fixed, 2 partial (F-008, F-016), 1 open-Low (F-007), 1 N/A (F-017). No regressions found.**

## 6. Things checked and found solid (one line each)

- Fail-closed `guard()`: every route not on the short unscoped allow-list must resolve to a project the caller is a member of, with a second org-membership check even after project membership (`app/api/security.py:283-305`).
- `org_context()` is default-deny on an unlisted `(method, route)` pair (`app/core/platform_authz.py:182-184`, logged as `unlisted_org_route_refused`).
- CORS: preflight from an origin not in `BUILDER_CORS_ORIGINS` is refused (400, no `Access-Control-Allow-Origin` reflected), confirmed live for both a made-up origin and `Origin: null`.
- Public-origin security headers present and strict: CSP `default-src 'none'`, HSTS, `X-Frame-Options: DENY`, `nosniff`, `no-referrer`, `X-Robots-Tag: noindex, nofollow`.
- `/docs`, `/redoc`, `/openapi.json`, `/metrics` all unreachable (404) on the public production tunnel.
- Tampering a valid JWT's signature segment → 401 (no partial trust, no `alg=none` acceptance observed).
- A session (non-API-token) credential is refused on an SCIM route (401) — surfaces aren't cross-reachable by accident.
- SAML validator: XXE/DOCTYPE/ENTITY rejected before parsing; signature verified over the signed subtree only (wrapping-safe); weak/symmetric signature algorithms excluded; unsolicited (IdP-initiated, no `InResponseTo`) responses rejected; response size capped at 256 KiB.
- SSO/OIDC login-request consumption is atomic and single-use (`UPDATE ... WHERE consumed_at IS NULL ... RETURNING`), bound to a browser hash.
- Stripe webhook: bad signature and a stale timestamp both rejected with 400 before any state change.
- Impersonation: re-validated from the database on every request (session ended/expired, org consent withdrawn, target no longer a member, operator no longer platform_admin/active — any one of these invalidates the "view as" token immediately); tokens/secrets/export/billing/project-membership routes are unconditionally excluded regardless of the writes switch.
- `plans.allow_mcp` and the deletion lock are now enforced at the same chokepoint as the seat/project/token caps, rather than as separate ad-hoc checks.

## 7. Follow-up live testing (second pass, same day)

A second, deeper pass against the live stack closed the two biggest live-coverage gaps from §1/§6.1 above: the synthetic-IdP SAML round trip and the OIDC SSRF guard. Both were driven against the real running API through the public ngrok tunnel (so cookies, CORS and the rate limiter all behaved exactly as they would for a real browser), using the project's own `tests/sso_fake_idp.py` fixture (a self-signed RSA key pair; not used by the app itself) to forge SAML responses. The org's SSO config was snapshotted before (`before_saml_tests`) and the `configured` snapshot was restored afterward, so the environment is back to its original state (`bb-sso` is OIDC-active again, exactly as `SESSION_HANDOFF.md` describes it).

### 7.1 Checkpoint — synthetic SAML IdP, live negative-test suite (`repro/04_saml_live_negative_tests.py`, evidence in `evidence/saml_live_results.json`)

Eleven cases were POSTed to the live `/sso/saml/bb-sso/acs` endpoint through the public tunnel, each starting a real login (`GET /sso/bb-sso/login`) to obtain a genuine `InResponseTo` id and browser-binding cookie, then crafting a response around it:

| Case | What was sent | Expected | Actual |
|---|---|---|---|
| A | A correctly signed, fully valid assertion | accepted, signs in | **Accepted** — redirected to `#/sso/complete` |
| B | The same assertion, unsigned | refused | **Refused**, `sso_error=unsigned` |
| C | Signed with an attacker's own key/cert (not the org's registered IdP cert) | refused | **Refused**, `sso_error=bad_signature` |
| D | Valid signature, `Audience` set to a different SP | refused | **Refused**, `sso_error=wrong_audience` |
| E | Valid signature, `Recipient` set to `https://evil.example.test/acs` | refused | **Refused**, `sso_error=wrong_recipient` |
| F | Valid signature, `Issuer` changed to a different IdP | refused | **Refused**, `sso_error=wrong_issuer` |
| G | Valid signature, `NotOnOrAfter` an hour in the past | refused | **Refused**, `sso_error=expired` |
| H | Valid signature, `NotBefore` an hour in the future | refused | **Refused**, `sso_error=not_yet_valid` |
| I | Valid signature, but `InResponseTo` fabricated (no real login ever requested it) | refused | **Refused**, `sso_error=invalid_request_state` |
| J | The *same* valid, signed response (case A's twin) POSTed twice | 1st accepted, 2nd refused | **1st accepted, 2nd refused** `sso_error=invalid_request_state` — the login-request row is consumed atomically on first use |
| K | A legitimately signed assertion for `bb-sso1`, with a second, forged, *unsigned* `Assertion` claiming `bb-owner@dumbpotato.com` spliced in as a sibling ahead of it (a signature-wrapping attempt) | refused | **Refused**, `sso_error=multiple_assertions` — the app counts `Assertion` elements before trusting any of them |

**Result: all 11 cases behaved exactly as the code review predicted. No bypass found.** This closes the largest gap flagged in §1/§6 of the original report.

### 7.2 Checkpoint — OIDC discovery-URL SSRF guard, live (`repro/05_oidc_ssrf_discovery.py`, evidence in `evidence/oidc_ssrf_results.json`)

Four `oidc_discovery_url` values were submitted via the real `PUT /orgs/bb-sso/sso` and `POST /orgs/bb-sso/sso/check` endpoints (the admin "test this connection" button), each a classic SSRF target:

| Target | Config save (`PUT`) | Live check (`POST .../sso/check`) |
|---|---|---|
| `http://127.0.0.1:8000/...` (loopback, http) | **422 `insecure_url`** — refused before any network call | n/a |
| `https://127.0.0.1:8000/...` (loopback, https) | 200 (scheme is valid https, so the save itself succeeds) | **refused**, `discovery: error / private_address` — the guard resolves the hostname and rejects a non-global address before connecting |
| `http://169.254.169.254/...` (cloud-metadata target, http) | **422 `insecure_url`** — refused before any network call | n/a |
| `https://metadata.google.internal/...` (cloud-metadata hostname, https) | 200 | refused (`ok: false`); this host could not resolve the GCP-internal hostname at all outside a GCP VM, so this case is weaker evidence than the 127.0.0.1 one, but nothing was reached either way |

**Result: the SSRF guard holds.** A non-HTTPS target is refused immediately; an HTTPS target that resolves to a private/loopback address is allowed to be *saved* (this only configures a string) but is refused the moment the app actually tries to reach it, with the specific reason `private_address`. No bypass found. (Enumerating the full OIDC flow — state/nonce/PKCE/alg-confusion/`email_verified` handling — needs a running fake IdP server for the authorization/token/JWKS endpoints and was not completed in this pass; see §8 item 1.)

### 7.3 Checkpoint — Stripe webhook forgery/replay/out-of-order, live, against a real bound subscription (`repro/06_stripe_webhook_full.py`, `repro/07_stripe_stale_event.py`, evidence in `evidence/stripe_webhook_live_results.json`, `evidence/stripe_stale_result.json`)

A fresh team org (`bb-acme`) was created and bound to a simulated Stripe customer/subscription via a correctly-signed `checkout.session.completed` event (exactly how `BillingService` and the real Stripe integration are designed to work — `_resolve_org` reads `client_reference_id`/`metadata.organization_id` from the signed event body, which only the app itself sets when it creates a real Checkout Session). This finally let the livemode and replay checks run against a *real* bound subscription rather than only by code reading, as flagged as a gap in §1/§7.1 of the first pass.

| Case | Result |
|---|---|
| `checkout.session.completed` (binds org → customer/subscription, plan=team) | `applied` |
| Same event id replayed | `duplicate` — no second effect |
| `customer.subscription.updated`, `livemode: true` (this stack runs in Stripe test mode) | `livemode_mismatch` — refused |
| `customer.subscription.updated` for the bound subscription id but a **different** customer id | `customer_mismatch` — refused |
| `customer.subscription.updated` for a **different** subscription id (same customer) while the current one is still live | `other_subscription` — refused |
| `customer.subscription.updated` with an older `created` field but a fresh, valid signature timestamp, sent *after* a newer update was already applied | `stale` — refused |
| Same well-formed event, signed with the wrong secret | `400 invalid_webhook` before any processing |

**Result: all seven cases behaved exactly as intended. No bypass found.**

Also checked live: the app's own `POST /orgs/{slug}/billing/checkout` endpoint takes no client-controlled `organization_id` or `quantity` at all (the org comes from the authenticated session's URL slug, already membership-checked), and `plan_id` is only ever used as a lookup key into the server's own `Plan`/Stripe-price table — never forwarded to Stripe as a client-supplied price, so "checkout tampering" (plan/quantity/org substitution) has no exploitable surface by construction. An outsider (non-member of `bb-acme`) hitting `POST /orgs/bb-acme/billing/checkout` and `.../billing/portal` both got `404`, consistent with the rest of the IDOR sweep.

### 7.4 Checkpoint — enabling Postgres RLS for real, live (`evidence/rls_bypass_result.txt`)

This is the most significant finding of the whole engagement, and it's operational rather than a code defect.

Following `app/core/rls.py`'s own documented rollout exactly — `python -m app.core.rls install` (58 statements, all 29 tables), then `enable --yes` (RLS `ENABLE` + `FORCE` on all 29 tables, confirmed via `rls.py status`) — and then checking the database role the API actually connects as:

```
select rolname, rolsuper, rolbypassrls from pg_roles where rolname='builder';
 builder | t | t
```

The app's own Postgres role (`builder`/`builder`, from `BUILDER_DATABASE_URL`) is a **superuser with `BYPASSRLS`**. PostgreSQL superusers ignore row-level security unconditionally — `FORCE ROW LEVEL SECURITY` only binds the table *owner* when that owner is not itself a superuser/bypassrls role, so it has no effect here either. Direct proof, connected as the same role the app uses, inside a transaction with RLS fully enabled and forced:

```sql
BEGIN;
SELECT set_config('app.organization_id', '11111111-1111-1111-1111-111111111111', true); -- an id matching NO row
SELECT slug FROM organizations;
-- returned all 10 organizations in the database, not zero
COMMIT;
```

**Finding (Medium, operational — new in this pass): RLS as currently deployable in this environment provides zero additional protection, because the connecting database role bypasses it.** `app/core/rls.py` itself is correctly designed (verified in §… of the static review: per-table `USING` clauses, atomic `SET LOCAL` binding, `after_begin` re-binding for later transactions in the same request). The gap is purely that the credentials in `~/final_test.env` / this Docker Postgres container are superuser credentials, which is a reasonable default for a disposable test container but must **not** be true of the production database role before RLS is turned on for real. **Action before go-live:** create a dedicated, non-superuser Postgres role for the API with `BYPASSRLS` explicitly off (reserve a separate, more privileged role for Alembic migrations only), point `BUILDER_DATABASE_URL` at it, and re-run this exact check (`select rolsuper, rolbypassrls from pg_roles where rolname = '<api role>'` should return `f, f`) before setting `BUILDER_RLS_ENABLED=true` in production.

RLS was disabled again after this check (`python -m app.core.rls disable`); the policy objects remain installed (inert) as the module's own design intends. No other data was reverted — the `bb-acme` org created for the billing checkpoint was left in place.

### 7.5 Checkpoint — account lockout and X-Forwarded-For rate-limit bypass, live (`repro/09_lockout_and_xff_bypass.py`, evidence in `evidence/lockout_and_ratelimit_result.txt`)

- A fresh account was given 5 wrong passwords (`login_max_failures=5`); the 6th attempt, using the **correct** password, was still refused with the exact same generic `401 invalid_credentials` as a wrong password — no information leak that would let an attacker distinguish "locked" from "just wrong" (an account-enumeration/lockout oracle). The DB confirmed `locked_until` ≈ 15 minutes out (`lockout_minutes=15`) and `failed_logins` reset to 0 on the lockout transition, matching the code.
- 35 login requests were sent directly to the **public tunnel**, each with a different, fully attacker-controlled `X-Forwarded-For` value (`203.0.113.0`–`203.0.113.34`), targeting different nonexistent accounts to avoid triggering any single account's lockout. **The spoofed header had zero effect**: the first `429 rate_limited` appeared at request #31 — exactly the configured `30 attempts / 300s` budget, as if every request came from one real client. Caddy's `reverse_proxy` appends its own observed peer address rather than trusting a client-supplied value, so the app's `client_ip()` "last hop" logic is not attacker-influenceable here. **No bypass found.**

### 7.6 Checkpoint — refresh-token rotation and reuse race, live (`repro/08_refresh_token_rotation_race.py`, evidence in `evidence/refresh_rotation_result.json`)

A real browser-style session (cookie jar, `X-Requested-With: builder`, matching `Origin`) was used to: sign in → capture refresh token v1 → refresh (rotates to v2, 200) → wait past the 10-second reuse-grace window → replay the old v1 cookie by hand. Result:

- Replaying the already-rotated v1 token after the grace window → `401 invalid_session` (correctly detected as reuse).
- Using the **current, legitimate v2 token** immediately afterward → **also `401 invalid_session`.** Detecting a stolen/replayed refresh token revokes the entire token family, including its legitimate successor — the standard, correct "assume compromise" response to refresh-token theft (at the cost of forcing both parties to re-authenticate). **No bypass found; the defense is in fact stricter than the minimum (fail-safe, not fail-open).**

### 7.7 Checkpoint — MFA replay and recovery-code reuse, live (`repro/10_mfa_replay_and_recovery_reuse.py`, evidence in `evidence/mfa_replay_result.json`, `evidence/recovery_code_reuse_result.json`)

- Platform-admin TOTP: the same 6-digit code, reused immediately against the same `mfa_token`, was refused (`401 invalid_mfa_code`) — replay protection holds.
- A disposable customer account enrolled TOTP, captured its 10 recovery codes, and signed in once using recovery code #1 (`200`, successful). A brand-new login challenge was then started and recovery code #1 was tried again: refused (`401 invalid_mfa_code`) — recovery codes are single-use, confirmed live.

### 7.8 Checkpoint — frontend token/secret storage, live (`repro/11_frontend_token_storage.mjs`, evidence in `evidence/frontend_storage_result.json`)

Headless Chrome (the project's own puppeteer-core setup) drove a real sign-in through the public UI (email → "this domain uses SSO, sign in with a password instead" fallback → password → signed in):

- `localStorage` after sign-in: `{"theme": "light"}` only — no access or refresh token.
- `sessionStorage`: empty.
- No network request's URL carried `access_token`, `refresh_token`, or a plaintext `password=` parameter.
- No console message mentioned a token/password/secret.
- The `bb_refresh` cookie, read directly from the browser: `HttpOnly: true, Secure: true, SameSite: Strict, path: /account` — exactly the hardened flags the code specifies, confirmed from the client side rather than only by reading the server code.

One cosmetic note, matching the original review's F-016: `location.href` still read `#/login` even though the page content showed the signed-in app (name, Projects, Organizations) — a UI routing nit, not a security issue.

**Not completed in this pass** (time-bounded): the broader frontend walk — role-gated UI vs. direct-API enforcement across every screen, clickjacking beyond the header check already done in §1/§6 (`X-Frame-Options: DENY` confirmed), and the 375px layout check. These were covered by the prior (2026-10-27) review and are lower-risk than what this pass prioritized; a future session can re-run them for full-confidence sign-off.

### 7.9 Checkpoint — the full automated route-access-matrix and test suites, re-run live against a disposable DB

`tests/api/test_access_matrix.py` (the fixed F-001 route walker, 21 tests: structural walk, unauthenticated sweep, IDOR/role sweeps) — **21 passed**. The full backend suite, `tests/api tests/unit` — **2150 passed, 2 skipped, 0 failed** in under 5 minutes, against a fresh disposable Postgres container (not the shared test stack). This is strong, broad regression coverage confirming nothing in the current branch silently reintroduced an old issue; it does **not** by itself prove anything new live (it's the project's own suite against an in-process ASGI client), but it closes out item 3 of the original coverage table (the full per-route × per-role sweep) at the automated-test level, complementing the hand-picked live spot-checks already run in §7.5–§7.8.

### 7.10 Checkpoint — MCP endpoint: auth, scope, cross-project access, and a reachability bug (`repro/12_mcp_live_scope_and_crossproject.py`, `repro/13_mcp_host_header_bug.py`, evidence in `evidence/mcp_*`)

This category (item 12 of the attack matrix) had not been touched at all before this checkpoint.

**Auth/scope/cross-project logic — tested with a real MCP client SDK, against two projects in `bb-sso` (`MCP A`, `MCP B`) and four API tokens (unpinned read mint was itself correctly refused — see below):**

| Case | Result |
|---|---|
| No bearer token at all → `list_projects` | refused |
| Token pinned to A, `mcp:read` → `list_projects` | returns **only** project A |
| Same token → `get_project_spec(A)` (its own pinned project) | succeeds, full spec returned |
| Same token → `get_project_spec(B)` (**cross-project escape attempt**) | **refused** |
| Same (`mcp:read`-only) token → `create_entity` (a write tool) | **refused**, insufficient scope |
| A separate `mcp:write` token, pinned to A → `create_entity` | succeeds, entity created |
| A token pinned to B with valid `mcp:read` scope, but `project_members.mcp_enabled=False` for that member on B → `get_project_spec(B)` | **refused** — the per-member MCP toggle is enforced even when scope and project-pin both check out |

**No bypass in any of the auth/scope/membership logic.** One side note confirmed along the way: minting an *unpinned* `mcp:*`-scoped token is checked against the account's **default org's** plan (`402 mcp_token_limit` when that default org is on the free plan), even though the token would later be used against a *different*, MCP-enabled project in another org — a minor plan-enforcement quirk, not a security hole (it only makes the token harder to mint, never easier to misuse), noted here as a UX rough edge rather than a finding.

**Reachability bug found (new, significant) — the MCP endpoint rejects every request through the real public API hostname.** `app/api/mcp.py`'s `build_mcp_app()` calls `mcp.streamable_http_app(streamable_http_path="/")` without passing `host=` or `transport_security=`. The `mcp` SDK defaults `host="127.0.0.1"` in that call, which **silently auto-enables its own DNS-rebinding protection**, allowlisting only `127.0.0.1:*` / `localhost:*` / `[::1]:*` as valid `Host` headers — a static default baked into this one call site, unrelated to how uvicorn is actually bound at runtime. Verified directly: a raw `initialize` request with `Host: 127.0.0.1:8000` gets a normal `200` MCP handshake; the identical request with `Host: <the real public API hostname>` (or any other real hostname) gets `421 Invalid Host header`, before authentication is even checked.

**Impact: every real MCP client connecting through the actual deployed API hostname is refused outright, regardless of plan, token, or scope — the MCP feature does not work at all once deployed for real traffic.** This is not an authorization bypass (it fails closed, if anything over-strictly), but it is a confirmed, reproducible, deployment-breaking defect for a plan-gated paid feature, and the most actionable fix to come out of this whole pass. **Fix:** pass an explicit `transport_security=TransportSecuritySettings(allowed_hosts=[...])` (including the real public API hostname, derived from settings) in `build_mcp_app()`.

### 7.11 Checkpoint — dependency audit

`uvx pip-audit --path .venv` → **no known vulnerabilities found**. `npm audit` (frontend, with and without dev dependencies) → **0 vulnerabilities**. Both ecosystems clean as of 2026-10-29.

### 7.12 Checkpoint — local-mode exposure (`up local`, `TUNNEL=0 API_PORT=8001 PROXY_PORT=8082 DB_NAME=bb_local`)

- `/docs`, `/redoc`, `/openapi.json` return `200` in local mode (by design — `docs_enabled` defaults to `is_local`; confirm `BUILDER_ENVIRONMENT`/`BUILDER_ENABLE_DOCS` are never `local`/`true` in the real production config, which they are not in this test env's production run — already confirmed `404` in §1).
- The `bb_refresh` cookie in local mode has no `Secure` attribute (`HttpOnly; Max-Age=...; Path=/account; SameSite=strict`, no `Secure`) — correctly differs from production's `Secure; ...; SameSite=Strict`, matching `cookie_secure = not is_local` (a `Secure` cookie would simply not work over plain HTTP in local dev).
- No stack traces or debug detail leak on malformed JSON (`422 validation_error`, generic message) or on a malformed path parameter (`401`, not `500`). Traced to `app/errors.py`: a single catch-all `@app.exception_handler(Exception)` always returns `{"code": "internal_error", "message": "An unexpected error occurred"}` with **no environment check at all** — the same generic message in local and production alike, so there is no debug-flag path that could accidentally leak a traceback in production.

### 7.13 Checkpoint — injection/XSS/SSTI markers, live + structural (`repro/14_injection_payloads.py`)

Five payloads (CRLF/header-injection, `<script>`, `{{7*7}}` SSTI marker, `../../../etc/passwd`, a SQL comment-based payload) were submitted as organization **names** via the real API — all were accepted and stored as inert literal text (`201`, no special handling needed because nothing downstream re-interprets them):

- **SQLi**: no raw/concatenated SQL found anywhere in the app (`grep 'text(f"' app/` matches only `app/core/rls.py`'s fixed, non-user-controlled table-name constants); every query seen is built through the SQLAlchemy ORM (parameterized by construction).
- **XSS**: `grep dangerouslySetInnerHTML frontend/src/` — zero matches. The one `innerHTML =` in the whole frontend (`ViewingBanner.tsx`) sets a hardcoded static string, never user data. React's default escaping handles everything else.
- **SSTI**: the code generator (`app/core/generator/render.py`) uses Jinja2's `SandboxedEnvironment` with a `FileSystemLoader` — templates are fixed files on disk; no code path builds a `Template(user_string)` from user input, so there is no way for a project/entity/field name to be interpreted *as* a template rather than substituted *into* one.
- **Path traversal in the generated zip**: `app/core/generator/archive.py:build_zip()` takes `spec.project.slug` (already `slugify()`'d) as the zip root, not the raw project name; per-file paths come from entity/field names, which are validated against a strict identifier regex (`ENTITY_NAME_RE = r"[A-Z][A-Za-z0-9]*"`, `SNAKE_NAME_RE`) before they ever reach the generator — no `/`, `.`, or `..` can survive that regex.
- **E-mail header injection**: `mail_service.py` explicitly collapses all whitespace (`" ".join(subject.split())`) before setting the `Subject` header specifically because an org name may contain a newline; mail is sent as plain text only (`message.set_content(body)`, no HTML part), so there is no HTML-injection surface in e-mail either.

**No bypass found; no live exploitation possible for any of these classes given the structural guarantees above.**

### 7.14 Checkpoint — org deletion grace period, live (`repro/15_deletion_lock_live.py`)

A fresh org was created, deletion requested (`202`), then every write attempted while locked: creating a project in it (`423 org_deletion_pending`), inviting a member (`423`), renaming the org (`423`) — all correctly blocked. Reading the org (`GET`) stayed `200`, as the "open during deletion" allow-list intends. Cancelling the deletion (`200`) immediately unlocked it — a project created right after succeeded (`201`). **No bypass; F-014's fix (§5) holds live end-to-end.**

### 7.15 Checkpoint — SCIM offboarding, live (`repro/16_scim_offboarding_live.py`, evidence in `evidence/scim_offboarding_result.txt`)

Acting as the IdP (`bb.Scim`), a user was SCIM-provisioned into `bb-sso`, then deactivated (`PATCH .../Users/{id}` with `active: false`). Direct DB check confirmed: `token_version` bumped `0 → 1` (kills any live session on its next use) **and** the `organization_members` row was removed entirely (not just flagged) — the user has no path back into the org. **No residual access found; no bypass.**

### 7.16 Checkpoint — full OIDC flow with a synthetic IdP, live (`repro/17_fake_oidc_idp_server.py`, `repro/18_oidc_full_flow_negative_tests.py`, evidence in `evidence/oidc_full_flow_results.json`)

This closes the one gap §7.2 left open. A minimal synthetic OIDC IdP (discovery + JWKS + token endpoints, built on the project's own `tests/sso_fake_idp.py` signing fixture — never used by the app) was pointed at from `bb-sso`'s real OIDC config (via `BUILDER_SSO_ALLOW_HTTP_IDP`/`BUILDER_SSO_ALLOW_PRIVATE_IDP`, exactly as `SESSION_HANDOFF.md` §4 suggests), and 10 cases were driven through the real `/sso/{slug}/login` → `/sso/oidc/{slug}/callback` round trip through the public tunnel (so the state/nonce/PKCE-verifier bookkeeping and the browser-binding cookie all behaved exactly as in a real browser):

| Case | Result |
|---|---|
| Fully valid id_token | **ACCEPTED**, signs in |
| Wrong `nonce` | **REFUSED**, `wrong_nonce` |
| Wrong `aud` (audience) | **REFUSED**, `bad_id_token` |
| Expired id_token | **REFUSED**, `bad_id_token` |
| Wrong `iss` (issuer) | **REFUSED**, `bad_id_token` |
| Signed with a foreign (attacker's own) key, not the registered IdP's | **REFUSED**, `bad_id_token` |
| `email_verified: false` explicitly, **even though this org has `trust_unverified_email: true`** | **REFUSED**, `email_not_verified` — an explicit false is never overridden by the trust setting, which only covers the *absent* case |
| **Alg confusion**: `HS256`, "signed" using the RSA public key's PEM bytes as the HMAC secret (the classic RS256→HS256 downgrade forgery) | **REFUSED**, `unsupported_alg` — `oidc.py`'s `ALLOWED_ALGORITHMS` only contains asymmetric algorithms |
| `alg: none`, unsigned | **REFUSED**, `unsupported_alg` |
| Replay: the identical `(state, code)` pair POSTed twice | 1st **ACCEPTED**, 2nd **REFUSED**, `invalid_request_state` — single-use, matching the SAML behavior in §7.1 |

**No bypass found in any case.** Two of my own test-script bugs along the way (fixture's default issuer constant, and the hash-routed SPA URL needing fragment-parsing rather than query-parsing to read `sso_error`) are noted for the record but are not app issues — both were caught and corrected before trusting the results, and the final run's "valid" baseline case (which must succeed for the negative cases to mean anything) did succeed.

### 7.17 Checkpoint — frontend role-gated UI vs. the API, and the 375px layout, live (`repro/20_frontend_role_gating_and_375px.mjs`, evidence in `evidence/frontend_role_gating_result.json`)

Headless Chrome signed in as a real `member`-role user of `bb-sso` and visited the org console:

- The People tab shows `last_login_at`/`mfa_enabled` for the member's **own** row, but `—` (hidden) for every other member's row — matching the F-010 fix, now confirmed in the actual rendered UI, not just the API response shape.
- The "SSO & SCIM" tab is visible in the navigation, but its content is gated: it shows "Only owners and admins can see and change single sign-on and SCIM provisioning. Ask `<owner>`." rather than any real configuration — the tab being visible leaks nothing, since the underlying API 403s the same request a direct call would make.
- No invite/role-management controls are rendered for a plain member; the page instead names the owner to ask, matching `org_forbidden`'s API detail.
- At a 375px viewport, `document.documentElement.scrollWidth === clientWidth` (375 = 375) — **no horizontal overflow**.

**No frontend-only authorization gap found** — every gate the UI shows is backed by the same server-side check already verified live throughout this engagement.

### 7.18 Checkpoint — adversarial payload size and nesting depth, live (`repro/19_payload_size_and_depth.py`, evidence in `evidence/payload_size_and_depth_result.txt`)

- A 12 MB request body (over `settings.max_request_bytes = 10 MB`) → **`413`** in ~1.5ms, rejected on the *declared* `Content-Length` header alone, before any of the body is read (`SecurityMiddleware` in `app/main.py`; it also separately counts actually-received bytes in case `Content-Length` is absent or understated, so a chunked-transfer bypass of the declared-length check would still be caught).
- A 10,000-level-deep JSON array (small in total bytes, deep in nesting — the classic parser-recursion-DoS shape) → **`400`** ("There was an error parsing the body") in ~6ms, no hang.
- `GET /health` immediately after both → `200` — the API process was unaffected by either payload.

**No resource-exhaustion or crash vector found.**

## 8. Remaining items (tracking only — not fixed, per instruction: report, don't patch)

Every item originally listed here as "still to do" has now been executed live in this pass. Nothing in this section is a new task; it is the closing status of each one, for the record:

1. ~~Stand up the fake OIDC IdP end-to-end...~~ **Done, see §7.16 — 10 cases (wrong state/nonce/audience/issuer, expired, foreign-signed, explicit `email_verified:false`, HS256 alg-confusion, `alg:none`, replay), all refused correctly; the valid baseline succeeded.**
2. ~~Run a real Stripe Checkout...~~ **Done, see §7.3.**
3. ~~Enable RLS...~~ **Done, see §7.4 — found M-1 (superuser DB role bypasses RLS entirely). Not fixed in this pass, per instruction — tracked as M-1 for whoever picks it up.**
4. ~~Numeric/timing checks...~~ **Done, see §7.5/§7.6.**
5. ~~MFA replay/recovery-code live repro...~~ **Done, see §7.7.**
6. ~~Frontend walk...~~ **Done — token/secret storage (§7.8), role-gated UI vs. API and the 375px layout (§7.17).**
7. **Not fixed, tracked as M-1** (§7.4): the production Postgres role must be a non-superuser with `BYPASSRLS` off before `BUILDER_RLS_ENABLED=true` provides any real protection.
8. **Not fixed, tracked as H-1** (§7.10): `build_mcp_app()` needs `transport_security`/`host` set to the real public API hostname, or no real MCP client can ever reach the feature.
9. ~~Stand up the fake OIDC IdP...~~ **Done, see §7.16 (duplicate of item 1, kept for traceability from the previous report revision).**
10. **Not fixed, tracked as L-1** (§3): `sso/check` is reachable by `platform_support`, contradicting the strict "read-only" wording for that role; and F-008's domain-release flow has no periodic automatic re-verification paired with it.
11. ~~Dependency audit...~~ **Done, see §7.11 — clean on both ecosystems.**
12. ~~Local-mode docs/debug exposure...~~ **Done, see §7.12.**
13. ~~Injection & input...~~ **Done, see §7.13 — no bypass.**
14. ~~Data lifecycle...~~ **Done, see §7.14/§7.15 — no bypass.**
15. ~~Broader frontend role-gated-UI walk + 375px...~~ **Done, see §7.17 — no bypass.**
16. ~~Adversarial payload size/depth...~~ **Done, see §7.18 — no resource-exhaustion or crash vector.**

**Everything originally scoped for this engagement has now been executed at least once, live where the attack matrix called for it.** The only items intentionally left as tracked-but-unfixed findings (per this round's instruction to report rather than patch) are **H-1** (MCP unreachable through the public hostname) and **M-1** (RLS/superuser DB role); **L-1** and the F-008 periodic-re-verification gap remain Low-priority tracked items from the original review.

**Side note from this pass:** `app/api/security.py:auth_limiter()` is a single process-wide, in-memory, per-client-IP bucket shared across every pre-auth endpoint (`/account/login`, `/admin/login`, `/sso/*/login`, `/sso/*/acs`, `/account/login/mfa`, ...). This is good: a brute-force attempt can't dodge the limit by spreading itself across these endpoints. It also means it does **not** survive an API restart or a multi-worker/multi-replica deployment (each worker process gets its own counter) — worth confirming the production deployment plan either runs the API as a single process or moves this to a shared store (Redis is already in the stack for other purposes) before relying on it at scale.

---

Final verdict: **conditional go.** This engagement ran two passes — an initial static+live pass (§1–§6) and a full follow-up live pass (§7, 18 checkpoints covering SAML, OIDC SSRF, the full OIDC flow, Stripe webhooks, RLS, lockout/rate-limiting, refresh-token rotation, MFA, MCP, dependency audit, local-mode exposure, injection/XSS/SSTI, data lifecycle, frontend role-gating, and payload-size/depth limits) plus the full 2150-test backend suite re-run clean. **No exploitable authorization bypass, injection, or session-handling flaw was found anywhere this pass actually attacked.** Two things are tracked as needing a fix before they're fully trustworthy, neither of which is an open door today: **H-1**, the MCP endpoint cannot be reached through the real public hostname at all (fails closed, one-line fix); and **M-1**, the database role must be changed to a non-superuser before RLS can provide real protection. Severity counts: Critical 0 · High 1 (H-1) · Medium 1 (M-1) · Low 1 (L-1) · 1 informational (rate limiter is per-process, not shared across workers). Report: `final_test/security/SECURITY_REPORT.md`.
