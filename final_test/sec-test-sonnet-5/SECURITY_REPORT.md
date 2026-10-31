# Security test report — Backend Builder (session: sec-test-sonnet-5)

Final report. All 14 attack-matrix categories plus three extra deliverables from the original
brief: a full, non-vacuous route enumeration, a dependency audit, and a mutation-testing pass in
a scratch copy. Target: the production-mode stack behind the ngrok tunnel
(`https://cinderous-overfamiliar-sanford.ngrok-free.dev`), with specific exceptions noted per
finding (local/Mailpit stack for mail-dependent checks; a direct connection to the Caddy proxy or
Postgres container for two checks the tunnel itself couldn't reach). All accounts/orgs/projects
used are disposable test fixtures created by the repro scripts; no shared fixture (`bb-owner`,
`bb-sso`, staff accounts) was mutated, only read-only/negative calls were made against the shared
staff accounts. One temporary `ALTER TABLE ... ENABLE/FORCE ROW LEVEL SECURITY` was run directly
against the throwaway Postgres container for the RLS test and reverted immediately after,
confirmed back to its original state. The mutation-testing pass ran in a full rsync scratch copy
under the scratchpad directory (never the working tree) against its own disposable database,
both deleted after. No product code changed.

## 1. Verdict

**Go, with four things to fix first** (none Critical, all bounded, none require architectural
rework):

1. **Row-Level Security currently provides zero actual protection** — the application's own
   database role is a Postgres superuser with `BYPASSRLS` (`infra/10.1`). Fix before relying on
   RLS as a second wall of defense with real tenant data: give the running application a
   dedicated, non-superuser, non-`BYPASSRLS` role.
2. **A forged (correctly-signed) Stripe webhook can set any org to any paid plan for free**
   (`billing/7.2`) — bounded by needing the webhook signing secret, but worth closing: derive the
   granted plan from the Stripe price id, not from client-set metadata.
3. **MCP, a billed feature, is completely unreachable through the public URL** (`mcp/12.1`) — a
   missing Host-allowlist config, not itself exploitable, but MCP cannot work for any real
   customer today. Quick fix in `build_mcp_app()`.
4. **The per-IP auth rate limiter is a single shared budget for the entire public app**
   (`authn/1.3`), because `client_ip()` resolves to loopback for every request through this exact
   Caddy→ngrok chain. Worth understanding before relying on it for abuse response in production.

Two Medium findings are worth a product decision rather than an emergency fix: impersonation
consent defaults opt-out (`opconsole/8.1`), and project names are unique platform-wide rather
than per-org (`authz/3.7`). Everything else that was tested — and the overwhelming majority of
the attack matrix was — held up to deliberate, hostile abuse: authentication, MFA, tenant
isolation, API-token scoping, SAML/OIDC/SCIM validation (via a self-signed synthetic IdP),
Stripe webhook idempotency and tenant scoping, operator write-blocks, org deletion/offboarding,
MCP's own auth/scope checks once reachable, input handling, and a 33-mutation test of the
existing suite (31 killed, 2 explainable survivors) all came back solid.

## 2. Environment and what could not be tested

- Stack stood up via `final_test/harness/stack.sh restore configured && up production`.
- **Repeated session collision**: the shared stack (ports, `final_test/run/api.pid`,
  `final_test/logs/api.log` — none parameterized by port/mode in `stack.sh`) was torn down and
  restored **8+ times** over the course of this test by what looks like another concurrent Claude
  Code session on this machine also driving the harness (three separate `claude` processes were
  observed running at once at points). Each time, `stack.sh restore configured && up production`
  brought it back within 30–90s. This is now a confirmed, recurring operational fact about this
  harness, not a one-off: **it does not survive two concurrent users**, and every restore wipes
  disposable test data (never anything from the `configured` snapshot's real fixtures).
- The free ngrok tunnel also dropped individual connections under moderate load a few times
  (`RemoteDisconnected`/`BrokenPipeError`), independent of the outages above; all retried with
  backoff, and reconciled against a direct health check before trusting any resulting "failure."
- **The MCP endpoint cannot be reached through the public tunnel at all** (421, see `mcp/12.1`):
  every MCP-specific test had to run directly against the Caddy proxy (`127.0.0.1:8081`),
  bypassing only ngrok.
- The real Okta browser login was confirmed blocked per `SESSION_HANDOFF.md §4` (stale password);
  all SAML/OIDC negative testing used a self-signed synthetic IdP instead, as directed.
- Not completed, and explicitly not claimed as tested:
  - MFA org-wide enforcement on the MCP/API-token surface with a genuinely different, invited
    member (`mfa/2.5`) — got far enough to confirm the *owner-needs-own-MFA-first* guard
    (`mfa/2.4b`) but not the full multi-account chain; needs mail or a quiet local-stack window.
  - A live rerun of SAML signature-wrapping (`sso/6.2`) after its rig's early bugs were fixed —
    code-confirmed only.
  - Live browser-based frontend testing: DOM XSS, an actual clickjacking attempt, double-submit,
    back/refresh-after-logout. Static analysis only (grep for `dangerouslySetInnerHTML`, storage
    usage) plus the fact that every category-3/4 test calls the API directly with no UI at all and
    found server-side enforcement independent of the UI.
  - Stored/reflected XSS in generated-project output, SSTI reaching the code generator, path
    traversal in generated zip entries, command injection into generated output, MCP tool
    injection, SCIM filter/PATCH edge cases beyond basic lifecycle, TLS configuration specifics,
    default/bootstrap credential guessing, quota/seat race conditions under real concurrency,
    downgrade-over-limit, and migration up/downgrade with data (covered by the prior review, not
    re-run here).

## 3. Findings, ranked

### High

**infra/10.1 — Row-Level Security currently provides no protection: the application's database
role is a Postgres superuser with `BYPASSRLS`.**
`app/core/rls.py`'s own docstring states "we never grant BYPASSRLS to the app role" — that does
not match what is actually configured for `BUILDER_DATABASE_URL`'s role here. Live-confirmed:
with RLS temporarily enabled and forced on `organizations`/`projects` (two disposable test orgs,
reverted immediately after), a query run as the app's own `builder` role with
`app.organization_id` correctly set to org A's id still returned **both** org A's and org B's
rows. `SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname='builder'` →
`(builder, true, true)`. PostgreSQL never applies RLS to a superuser or a `BYPASSRLS` role,
regardless of `FORCE ROW LEVEL SECURITY` — there is no override. The policy SQL itself is
correct (verified via `pg_policy`), and `BUILDER_RLS_ENABLED=false` in this env anyway — but the
finding is deeper than "RLS is off": even with every switch in `app/core/rls.py` flipped on
today, RLS would still protect nothing while the app connects as this role. Fix: a dedicated,
narrowly-scoped Postgres role for the *running* application, not superuser, without `BYPASSRLS`
(migrations can keep a separate, more privileged role). Test reverted cleanly.

**billing/7.2 — A forged (but correctly signed) `checkout.session.completed` sets ANY purchasable
plan via `metadata.plan_id`, with no check against what was actually paid.**
`app/services/stripe_webhook_service.py:_apply_checkout` (~line 201-208). Live repro: a disposable
org on the free plan; a forged event with `payment_status=paid`, `client_reference_id=<org's real
UUID>`, and `metadata.plan_id="business"` (a real Stripe-billed plan — `enterprise` is
off-platform/custom and correctly has no effect, which is why a first attempt with that plan
looked like a non-finding) moved the org from `free` to `business`. No real Stripe Checkout
Session, customer, or payment ever existed. Precondition: the attacker already holds the Stripe
webhook signing secret (this test simulates exactly that compromise, using `bb.stripe_webhook`,
per the test brief) or an endpoint misconfiguration that lets them reach this route with a
validly-signed body. Fix: derive the granted plan from the Stripe price id on the line item (as
`_apply_subscription` already does via `_plan_for_price`), not from client-set metadata, or match
against a server-side record of the intended plan made when the real Checkout Session was created.

**mcp/12.1 — The MCP endpoint is completely unreachable through the public-facing URL (421
`Invalid Host header`), independent of authentication.**
Reproduced twice: an unauthenticated `initialize` call through the public ngrok tunnel → 421; the
identical request sent directly to the Caddy proxy on `127.0.0.1:8081` (bypassing only ngrok) →
200, normal MCP response. `app/api/mcp.py` configures no `allowed_hosts`/transport-security
setting — the `mcp` package's Streamable HTTP transport applies its own default Host-header
allow-list (a sane DNS-rebinding defense for local dev) and the app never widens it to include
`settings.public_api_url`'s real hostname. Impact: MCP (a billed, plan-gated feature —
`plans.allow_mcp`, `max_mcp_tokens`) is non-functional for every customer reaching the app through
its real public URL — the normal case for any deployment behind a reverse proxy/CDN/tunnel, not a
corner case. Not itself exploitable; a product-availability bug with a security-adjacent cause.
Fix: configure the `mcp` library's allowed hosts from `settings.public_api_url` (and likely
`public_app_url`) in `build_mcp_app()`.

**authn/1.3 — Per-IP rate limiting (and `client_ip` in the audit log) is defeated by the
Caddy→ngrok proxy chain; every public request collapses to one shared bucket.**
`app/api/security.py:65-73`. Live evidence, reproduced on two separate occasions including a raw
`GET /admin/audit?action=account.login_failed` dump of 36 consecutive rows: `client_ip` is
`127.0.0.1`/`::1` for every row, including ones generated through the public tunnel. Root cause:
`BUILDER_TRUST_PROXY_HEADERS=true` makes `client_ip()` trust the *last* hop of
`X-Forwarded-For`; Caddy's `reverse_proxy` appends its own immediate-peer address as that last
hop, and its immediate peer here is always the local ngrok agent (loopback) — not the real
internet client, even though ngrok itself injects the real client IP earlier in the same header.
Impact: the 30-request/300-second auth rate limiter (`config.py:29`) becomes one global budget
for the entire public app — any single user's or attacker's burst of ~30 requests exhausts it and
blocks everyone else's login/register/refresh for the window; this session triggered that effect
on itself by accident, repeatedly, just from normal testing traffic. Fix: have Caddy preserve the
real client address it already sees in the inbound header rather than only appending its own
peer, and configure the app to trust the right hop count — or avoid "trust the last hop" when
there's more than one local proxy stage between the public edge and the app.

### Medium

**authz/3.7 — Project slug/name uniqueness is enforced globally, not scoped per org.**
`app/models/project.py:17` (`slug: ... unique=True`, no `organization_id` in the constraint).
Live-confirmed: two completely unrelated disposable orgs — org A creates a project named
`sectest-global-slug-ae0a8e` → 201; org B (different owner, no relationship to org A) creates a
project with the exact same name → 409. Impact: any org can permanently deny a project name to
every other org on the platform forever (squatting on common names, or a guessed competitor
name); the 409 is also a minor cross-tenant signal. Fix: composite
`UniqueConstraint("organization_id", "slug")`.

**opconsole/8.1 — A brand-new org's `allow_impersonation` defaults to `True` (opt-out), not
`False` (opt-in).**
`app/models/platform.py:234`. Live-confirmed via `GET /orgs/{slug}/policies`. Not a direct
exploit — an operator still needs `platform_admin` + `impersonate:write` + an audit trail + the
hard write-blocks (which tested perfectly solid, see `opconsole/8.2`) — but it is the opposite of
a consent model: every org silently permits platform staff to "view as" its members unless
someone notices the policy and turns it off. Fix: default to `False`, treat turning it on as the
explicit consent action.

**setupnotes/13.1 — Password login/signup works on a domain with an active, verified SSO org
("enforce SSO" is not built).**
Live-confirmed: registered a brand-new disposable account at
`sectest-ssogap-<random>@dumbpotato.com` (bb-sso's real, verified SSO domain) via plain
`POST /account/register` → 201; logged in with that password immediately after → 200, full
session. `platform_auth_service.login()` has no reference anywhere to SSO/domain policy. Matches
`NOTES_FOR_TEST_SESSIONS.md` item 2 exactly — a known, previously-documented gap, not a new
regression. Only affects accounts that have never SSO-signed-in (once a password account does,
its password is wiped — see `setupnotes/13.4`). Suggested fix (already tracked as an open item):
an org policy to refuse password login/signup for its verified domain(s) once SSO is active, with
a break-glass admin override.

### Low

- **setupnotes/13.2** (confirmed by code): invitation mail has no `Date` or `Message-ID` header —
  `app/services/mail_service.py:_send_sync()` builds an `EmailMessage` with only
  From/To/Subject/body; `smtplib` does not auto-add either header. Matches the exact symptom
  observed in setup (GoDaddy filed the mail under Spam). Easy fix: add both headers via
  `email.utils`.
- **authn/1.8** (code-confirmed): `must_change_password` is enforced on every admin request, not
  just at login (`security.py:544`) — not dynamically exercised live (no safe way to flip the
  flag on a shared staff account without a DB write), but the code path is unambiguous.
- **mfa/2.4 / mfa/2.4b** (code-confirmed, live partially blocked by the shared rate limiter): the
  negative legs of "disabling MFA needs both password and a valid code" were live-confirmed; the
  "both correct → success" leg and the "owner needs their own MFA before requiring it org-wide"
  check are confirmed by code reading only, after repeated rate-limiter interference.
- **sso/6.2** (code-confirmed only): SAML signature-wrapping — `validate_response()` counts
  `saml:Assertion` elements and refuses anything but exactly one, before any signature check
  runs, structurally closing this attack class. A live rerun was repeatedly interrupted by the
  session-collision outages; the sibling SAML checks (signature, foreign-key, audience, XXE) were
  all re-verified live successfully.

## 4. Test-script bugs found and self-corrected (for the record — not product findings)

In the interest of not overclaiming, several apparent "findings" during this session turned out
to be bugs in the repro scripts themselves, caught by re-verifying before writing them up. Listed
so nobody re-chases them in the product:
- `sso_error_of()` parsed the redirect's query string, but the app is a hash-routed SPA
  (`#/path?sso_error=X`) — the real params are in the URL fragment. This made the first SAML/SSRF
  run look like "nothing blocked" across the board; fixed before trusting any result.
- The SSRF-guard check read a non-existent `items` field from `/sso/check`'s response; the real
  shape is `{"ok": bool, "checks": [{"name","status","detail"}]}`.
- `/orgs/{slug}/sso/test` returns `login_url`, not `url`.
- The billing tests compared `.get("plan_id")` on `GET /orgs/{slug}/plan`, but the real field is
  nested at `plan.id` — every billing test vacuously "passed" (`None == None`) on the first run,
  including the one that eventually found `billing/7.2`; re-verified with the right field first.
- `requests.Response.__bool__` is `status_code < 400`, not "is not None" — a debug print using
  `if r else 'n/a'` showed "n/a" for a *correct* 403. Cosmetic only; the real pass/fail logic used
  `.status_code` directly.
- The checkout-tampering test's first attempt used plan `enterprise`, which isn't Stripe-billed
  at all (off-platform/custom) — so nothing moved, for an uninteresting reason. Retried with
  `business` (a real Stripe-billed plan) and got the real, confirmed answer.
- An early MCP auth test failed uniformly across every variant (no-auth, wrong-scope, right-scope
  alike) — not because MCP auth was broken, but because the mint of the "correct" token itself
  had failed with 402 (free plan's `max_mcp_tokens=0`, and separately because an API token's
  "default org" for quota purposes isn't the org you just created unless you pin the token to a
  project in it). Fixed by bumping the plan and pinning the token correctly before judging anything.
- Several multi-account tests transiently failed with `None`/zero-looking results that turned out
  to be the shared tunnel-wide rate limiter (see `authn/1.3`) or a brief stack outage from the
  concurrent-session collisions (ngrok's own "endpoint offline" page returning as if it were a
  clean `404` from the app) — never written up as a product finding without first confirming
  `/health` was genuinely healthy and retrying in isolation.

## 5. Full attack-matrix coverage (all 14 categories)

| # | Item | Tested | Result |
|---|---|---|---|
| 1 | Brute force / lockout | Yes | Solid (generic 401 for wrong-password vs. locked — anti-enumeration by design) |
| 1 | Case/Unicode e-mail lockout bucketing | Yes | Solid |
| 1 | Rate-limiter bypass via X-Forwarded-For | Yes | No spoofing bypass found, but see `1.3` — the *real* IP tracking is broken for an unrelated reason |
| 1 | JWT tampering (alg=none, tampered payload, bad signature, wrong audience, garbage) | Yes | Solid |
| 1 | Cookie flags, CSRF, CORS | Yes | Solid |
| 1 | Session fixation | No | Not attempted |
| 1 | Password reset/change flow | Partial | No self-service "forgot password" exists (admin-reset only, by design); change-password not separately abuse-tested |
| 1 | must_change_password bypass | Code-read | Solid |
| 2 | TOTP replay, recovery codes, challenge-token cross-surface | Yes | Solid |
| 2 | TOTP window abuse | No | Not attempted |
| 2 | Enrolment hijack | Code-read | Solid |
| 2 | Disabling MFA without proof | Partial | Negative legs live; positive leg code-confirmed only |
| 2 | Platform-staff MFA bypass | Yes | Solid (`require_admin` checks `mfa_satisfied` every request) |
| 2 | Org require-MFA bypass (session/API token/MCP) | Partial | Owner-needs-own-MFA-first confirmed; full chain not completed |
| 3 | Full per-route enumeration via effective_route_contexts | Yes (via §6) | Solid, 217 routes, F-001 fixed |
| 3 | Unauthenticated/outsider sweeps, IDOR, mass assignment, last-owner protection, cross-org project access | Yes | Solid |
| 3 | Privilege escalation (admin→owner) | Partial | Last-owner protections solid; admin-makes-owner mutation-tested (M10, killed), not separately live-driven |
| 3 | SCIM bearer on app routes and reverse | Yes | Solid (§6) |
| 4 | Scope enforcement, destructive actions, token-minting-tokens, pinned-token escape, revocation | Yes | Solid (incl. review F-002 fixed) |
| 4 | Expired tokens | No | Not separately tested (revoked: solid) |
| 4 | Quota races | No | Not attempted |
| 5 | NUL bytes, oversized/deep bodies, header injection, security headers, open redirect | Yes | Solid (review F-003 stays fixed) |
| 5 | Stack-trace leakage on malformed authenticated input | Yes | Solid |
| 5 | XSS (stored/reflected in frontend), SSTI in generator, zip path traversal, command injection, e-mail HTML/URL injection | No | Not attempted — needs a browser or the generator pipeline |
| 6 | SAML: unsigned/foreign-signed/wrong-audience/XXE | Yes | Solid, live with a synthetic IdP |
| 6 | SAML: wrong-issuer/recipient/expired/unsolicited/replay/signature-wrapping | Code-read | Solid by code; live rerun interrupted by session collisions |
| 6 | OIDC discovery_url SSRF | Yes | Solid |
| 6 | SCIM tenant isolation / bearer lifecycle | Yes | Solid |
| 6 | SCIM off-domain provisioning, filter/PATCH quirks, group mapping | Partial | Off-domain refused (400), not scored as pass/fail — informational |
| 6 | Okta/Entra live round-trip | No | Blocked per SESSION_HANDOFF §4; synthetic IdP used throughout |
| 7 | Stripe webhook: bad signature, malformed, replay, stale/out-of-order, other customer, livemode | Yes | Solid (review F-004 stays fixed) |
| 7 | Stripe webhook: checkout plan/quantity tampering | Yes | **Confirmed (7.2)** |
| 7 | Checkout/portal access by non-admin | Yes | Solid |
| 7 | Quota/seat/project races, downgrade-over-limit, past_due bypass | No | Not attempted (past_due *status* behaviour mutation-tested, M18, killed) |
| 7 | Plan-flag enforcement (allow_sso/allow_scim/allow_mcp) | Yes (code + mutation) | Solid |
| 8 | Operators never see customer secrets, audit never leaks secrets | Carried from review canary | Solid |
| 8 | Support strictly read-only | Yes | Solid |
| 8 | Impersonation consent | Yes | **Confirmed default-opt-out (8.1)** |
| 8 | Impersonation write-block / hard-blocked routes / banner / audit | Yes | Solid |
| 8 | Operator rotate of SCIM | No | Not attempted |
| 8 | Org export tenant scoping | Yes | Solid |
| 9 | dangerouslySetInnerHTML / DOM XSS sinks, token/secret storage | Static analysis | Solid |
| 9 | Clickjacking / CSP / security headers | Yes | Solid |
| 9 | Source maps | Yes | Solid, not served |
| 9 | DOM XSS (live), double-submit, back/refresh-after-logout, role-gated UI vs API | No | Needs a headless browser session |
| 10 | Docs/openapi exposed outside local | Yes | Solid |
| 10 | DB RLS: read across orgs with the app's own role | Yes | **Confirmed gap (10.1)** |
| 10 | TLS settings, dependency audit, default/bootstrap credentials, secret key handling | Partial | Dependency audit done (clean); others not attempted |
| 11 | Deletion lock bypass via project/token creation | Yes | **Fixed, confirmed (review F-014)** |
| 11 | Grace period cancel | Yes | Solid |
| 11 | Offboarding cascade (member removal → project memberships) | Code-read, consistent with live pinned-token behaviour | Solid |
| 11 | SCIM-specific offboarding, migration up/downgrade with data, secret backups | No | Not attempted (migrations covered by the prior review) |
| 12 | MCP reachability through the public URL | Yes | **Confirmed gap (12.1)** |
| 12 | MCP auth, scope, per-member mcp_enabled gate, cross-project access | Yes | Solid |
| 12 | MCP org-MFA enforcement | Code-read | Solid |
| 12 | MCP tool injection | No | Not attempted |
| 13 | NOTES items 1-9 re-verified with a reproducer | Yes (items 2, 5, 6, 9 directly; 1/3/4/7 were already context/by-design/Okta-blocked) | Items 2 and 5 confirmed as open gaps; 6 and 9 confirmed as working-as-designed |
| 14 | Public exposure (docs, openapi, metrics, health, SCIM/SSO discovery) | Yes | Solid |
| — | Full non-vacuous route enumeration (review F-001) | Yes | **Fixed, confirmed** — 217 routes, all consistency checks pass |
| — | Dependency audit (pip-audit, npm audit) | Yes | Solid, zero known vulnerabilities |
| — | Mutation testing in a scratch copy | Yes | 31/33 killed; 2 explainable survivors (one is the still-open F-009, one is a weak/cosmetic mutant) |

## 6. Re-check of the 17 earlier findings (review/review_PLATFORM_SAAS_PLAN.md)

| ID | Then | Now |
|---|---|---|
| F-001 (vacuous route walker) | High | **Fixed** — 217 routes enumerated, every consistency check passes |
| F-002 (API tokens: destructive org actions) | High | **Fixed** — confirmed live |
| F-003 (NUL byte 500) | Medium | **Fixed** — confirmed live |
| F-004 (Stripe `data.object` not a dict → 500) | Low | **Fixed** — confirmed live |
| F-005 (pre-hijack via SCIM/JIT/invite-by-id) | High | **Fixed** — confirmed live/code; full SCIM/JIT live chain still not independently re-driven |
| F-006 (admin token amr not checked) | Low | **Fixed** — confirmed |
| F-007 (`platform_support` can call `sso/check`, a live outbound fetch) | Low | Not re-checked |
| F-008 (verified domain claim is permanent, no release) | Medium | Not re-checked (an operator "release domain" endpoint exists per the admin route list — `/admin/sso/domains/{domain}/release` — not independently verified this session) |
| F-009 (audit detail sanitizer untested) | Medium | **Still open** — reproduced via mutation test this session (M09 survives) |
| F-010 (members see mfa_enabled/last_login_at) | Low | Not re-checked |
| F-011 (quota.denied audit missing actor_email) | Low | Not re-checked |
| F-012 (legacy project member outside org) | Medium | **Fixed going forward** — member removal now cascades to `project_members`; the original backfill gap for pre-existing data was not separately re-checked |
| F-013 (`allow_mcp` not enforced) | Medium | **Fixed** — confirmed by code and by mutation test (M20) |
| F-014 (deletion lock gap on project/token creation) | Medium | **Fixed** — confirmed live |
| F-015 (no organization_id in log context) | Low | Not re-checked |
| F-016 (minor deviations: no plan DELETE, no grandfathering, global Fernet key, etc.) | Low | Not re-checked |
| F-017 (agent-report accuracy) | — | Not applicable to this session |

## 7. Things checked and found solid (one line each)

- Account lockout after repeated bad passwords, with a deliberately generic error to avoid
  revealing "locked" vs "wrong password"; email normalization prevents a case-variant bypass.
- JWT `alg=none`, tampered payload, flipped signature byte, wrong audience, and garbage tokens
  are all refused with 401.
- Refresh cookie is `HttpOnly`, `Secure`, `SameSite=Strict`, scoped to `/account`; CSRF defense on
  `/account/refresh`; CORS never reflects an attacker or `null` origin.
- TOTP codes cannot be replayed across independent login challenges in the same 30s step;
  recovery codes are single-use with cosmetic format tolerance; MFA challenge tokens are bound to
  their audience/purpose and rejected cross-surface or tampered; disabling MFA needs both the
  password and a valid code (negative legs live).
- Every probed route refuses an unauthenticated caller; a non-member gets 404, not 403, on every
  route of an org, with no exceptions found; org slugs are exact-match, no case/whitespace IDOR;
  mass-assignment fields are ignored on registration and org creation; the last owner of an org
  cannot leave or self-demote; a user outside an org cannot read/write/join/transfer its project
  even holding the real UUID.
- API token scopes are enforced; a write-scope token still cannot do session-only actions
  (delete/transfer/role-change/checkout/portal/export); a token can never mint or list other
  tokens; a project-pinned token cannot reach org routes or a sibling project; a revoked token
  stops working immediately.
- NUL bytes, an 11 MiB body, and a 5000-level-deep JSON object are all refused cleanly; a
  malicious `X-Request-Id` is never echoed raw; every response carries the expected security
  headers; SSO redirects are always server-built, never from a query parameter; authenticated
  malformed-input probes never leak a stack trace.
- A synthetic SAML IdP's unsigned, wrong-key-signed, and wrong-audience assertions are each
  refused with their own specific reason; a correctly signed one passes every structural/crypto
  check; a Response with a DOCTYPE/ENTITY is rejected outright; an OIDC `discovery_url` pointing
  at loopback/link-local/private/`localhost` is refused (DNS-resolved and IP-checked); a SCIM
  bearer dies on revoke and an app bearer never works as a SCIM bearer.
- A forged Stripe webhook with a bad signature or malformed `data.object` never causes a 500; a
  duplicate event id and an older out-of-order event are both no-ops; an event citing a different
  customer than the one bound to the org is refused; a `livemode=true` event is refused on this
  test-mode platform; checkout/portal are session-only.
- Impersonation hard-blocks tokens/export/billing regardless of the writes switch; the org console
  stays look-only even with writes on; `platform_support` has no write permission at all,
  including `impersonate:write`; an org's own owner can export its data, a non-member gets 404.
- No `dangerouslySetInnerHTML` sink anywhere in the frontend; browser storage holds only a theme
  preference and a one-shot UI flag; no source maps served; docs/openapi disabled on the public
  tunnel, enabled in local mode.
- The org-deletion lock covers project and pinned-token creation; removing a member cascades to
  their project memberships in that org; an owner can cancel a pending deletion during the grace
  period, fully unlocking the org.
- MCP tool calls refuse no-auth and wrong-scope callers; the per-member `mcp_enabled` flag is a
  real secure-by-default gate; the same token cannot reach a different org's project through any
  tool; org `require_mfa` is enforced on the MCP surface too.
- What an unauthenticated internet client can reach is limited to intentionally-public discovery
  endpoints (SP metadata, OAuth protected-resource metadata) plus minimal health checks — no
  debug/metrics endpoint, no stack trace.
- Zero known vulnerabilities in the pinned Python or npm dependency sets.
- 217 real routes enumerated (not 0 — the old vacuous-walker bug is fixed), every structural
  consistency check passes, and a 33-mutation test of the existing suite in a scratch copy killed
  31/33, with the two survivors both individually explained rather than hand-waved.

---
Scripts: `repro/01_authn_session.py` … `08_operator_privacy.py` (+ `_common.py`, `_saml_forge.py`).
Raw findings: `findings.jsonl`. Logs: `logs/*.log` (incl. `mutate.log`, `pip-audit.log`).
