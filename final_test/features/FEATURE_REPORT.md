# FEATURE REPORT — session 2 (feature / QA test), 2026-10-29/30

## 1. Verdict
**Conditional GO for attaching real credentials, with one precondition and two fixes recommended first.**
No Blocker was found in product code: auth, orgs, roles, quotas (incl. races), Stripe webhook lifecycle, SCIM, SSO management, MCP,
impersonation, export, org policies, operator console and three generated projects (built, migrated, own tests green, booted, exercised) all behaved correctly.
Precondition (environment, not code): the Stripe **test account has no business name**, so real Checkout creation fails (`400 In order to use Checkout,
you must set an account or business name`); the same will happen for the platform's billing and for generated payments projects until that is set in the Stripe dashboard.
Major: project optimistic locking is not atomic (F-1) and project slugs are global across tenants (F-2).
Counts: **Blocker 0 · Major 2 · Minor 8 · Cosmetic 2** (plus 1 environment precondition). ~1050 recorded checks (`logs/results.jsonl`, `logs/ui_results.jsonl`); every FAIL in those files that is not listed below was a defect in my own test and was fixed/re-run.

## 2. Environment, and what could not be tested
Stack: `stack.sh up production` (Postgres container, migrations, built frontend, Caddy proxy, API, ngrok), mostly with `MAIL=sink` (Mailpit) and a raised auth rate limit
for bulk runs; default limits and real GoDaddy mail for the rate-limit and real-delivery checks (3 real mails sent). Drove the API directly (`journeys/`) and headless Chrome (`ui/`).
Could not test / not done (reason):
- Real Okta browser sign-in (handoff §4: password stale) and a synthetic SAML/Keycloak IdP — **not attempted** in this session (time); SSO covered via management API, discovery, error-redirects, ACS/callback failure paths, domain rules, plan fallback. JIT, seat cap on SSO, staff-refused, `email_not_verified` banner: not tested here.
- Second DNS domain verification (no DNS access, as documented). Unverified/foreign-domain paths tested.
- Stripe: real Checkout (account precondition above), billing portal, seat-quantity sync to Stripe, `stripe listen/trigger` (CLI present, not driven), test-card declines. Webhook lifecycle tested with signed events.
- UI: page sweep (all pages, 375/768/1280, light/dark, console/5xx/overflow/back/keyboard) for owner and member only; admin/outsider sweep ran once with a too-short wait and was discarded. Form-level UI journeys (create org, invite, checkout buttons), two tabs, slow network, offline UI states, 402/423/429 message wording in the UI: **not tested**.
- Operator console in the browser (staff TOTP UI), RLS flag on/off, invite expiry / trial expiry / clock skew (no time control), scheduled-deletion job (only operator "delete now" + grace change tested), kill-DB/Stripe mid-request, Redis/MinIO/Keycloak/OTLP features of generated projects (storage/files endpoints only checked for auth), 5000-row list (300 projects used).
- My own mistake: an operator `domain release` call released `dumbpotato.com` from `bb-sso` and a config PUT overwrote the OIDC config. Restored from the `configured` snapshot; later runs used a restored DB.

## 3. Failures / findings
### Environment precondition
**E-1 Stripe test account lacks a business name** — `journeys/j07_stripe.py` J7.01 (HTTP 502 `billing_provider_error` in the app); `journeys/j04_build_generated.py storage_payments` pay.start (422 `payment_rejected`, Stripe `invalid_request_error`). Fix: set the account/business name in Stripe dashboard. App error text is clean in both cases.

### Major
**F-1 Project optimistic locking is not atomic (lost updates).** `journeys/j03b_lock_and_lockout.py` (J3.lock_race2) and J3.lock_race. 8 parallel `PATCH /projects/{id}` carrying the same `version`: expected exactly one 200, got 3, then 3 and 4 winners (rounds `[1,3,4]`). Sequential stale write correctly 409. Fix: `UPDATE … WHERE id=:id AND version=:v` with rowcount check (or `SELECT … FOR UPDATE`). Same pattern likely applies to other versioned resources.
**F-2 Project slugs are unique across ALL tenants.** `journeys/j16_slug_global.py`. User A creates "Shared Name"; user B creating the same name gets `409 a project with this slug already exists` — a cross-tenant existence oracle, and common names ("Blog", "Shop") collide for unrelated customers. Non-ASCII names all collapse to slug `project`, so a second such project is a 409 with no way to see why (also hit while seeding projects named with emoji). Fix: unique per organization (and user for personal), auto-suffix on collision, or show/edit the slug in the create form.

### Minor
**F-3 Invitation accepts any string as e-mail** (`j03_orgs_projects_quotas.py` J5.15): `{"email":"not-an-email"}` → 201, consumes a seat, tries to send mail. Fix: validate e-mail format.
**F-4 SSO config accepts private/loopback/internal IdP URLs and can be activated** (`j08_sso.py` + manual run): `https://127.0.0.1/x`, `https://localhost/…`, `10.0.0.5`, `metadata.google.internal`, `internal.local` all saved (200) and `activate` returns 200; only `POST …/sso/check` reports `discovery: error private_address`. Fetch-time SSRF block works, so this is validation/UX; `last_test: ok` from the old config stays shown. Fix: reject at save, require a passing check before activate.
**F-5 Registration reveals whether an account exists** (J1.02b): duplicate register → `409 "an account with this e-mail already exists"`. Login itself is uniform (J1.14 pass).
**F-6 Account lock after 5 bad passwords is silent (suspected, from code `platform_auth_service.py:216`; live confirmation blocked by my own IP rate limit).** A locked user, even with the correct password, gets the generic `invalid e-mail or password`, never "locked for 15 minutes". The per-IP limiter (30/5 min across login+register+refresh) does show Retry-After (verified).
**F-7 Generated auth rate limit counts successful logins and refreshes** (`gen_auth.py`; `app/auth/ratelimit.py`): default `5/15minutes` per client address shared by login, refresh and magic-link consume; I hit 429 ("retry in 899 seconds") after 5 normal calls. Behind a proxy all clients share one address. The docstring documents it; consider counting only failures. Config values are Python constants, tunable.
**F-8 Mobile (375px) org People table clips**: role selects show "A⌄/M⌄" and dates "10/30/202" (`evidence/owner_mobile_org-people.png`). No page-level horizontal overflow anywhere in the sweep, but the table is unusable for role changes on phones.
**F-9 Invitation "pending" list and accept-by-id need a verified e-mail** (J5.22/J5.26): self-registered accounts get `403 email_not_verified` / empty list and can only accept via the mailed token link. I found no e-mail verification flow for platform accounts; confirm that is intended.
**F-10 `types.ts` vs OpenAPI drift (suspected)** (`logs/types_drift.log`): `PaymentsSizing` has flat fields while the API returns `{issues,sizing}`; the other 8 reported items are `extends`-parsing noise.

### Cosmetic
**C-1** Member view of Security tab reads "Only owners and admins can change security policies. Ask  t  ." (gap before the period, owner shown by display name only) — `evidence/member_desktop_org-policies.png`.
**C-2** Sidebar of the shell shows "Loading…" body for several seconds after every reload through ngrok (login refresh + 6 sequential calls; each project list load also fires a 404 `GET /projects/{id}/auth` per project → red console noise).

## 4. Coverage matrix (journey × role; P = pass, F = finding above, – = not tested)
| Journey | anon | individual | owner | admin | member | outsider | op admin | op support |
|---|---|---|---|---|---|---|---|---|
| 1 sign-up/login/refresh/pw/lockout | P (F-5,F-6) | P | P | – | P | P | P | – |
| 2 account: tokens, TOTP, recovery | – | P | P | – | P | – | – | – |
| 3 projects, locking, locked-org | P | P | P (F-1,F-2) | – | P | P | – | – |
| 4 builder core + hostile specs | – | P | P | – | – | – | – | – |
| 5 organizations (invite mail, roles, transfer, deletion) | P | – | P (F-3,F-9) | P | P | P | P (delete-now) | – |
| 6 plans/quotas/races | – | P | P | – | – | – | P (overrides) | – |
| 7 Stripe webhooks / lifecycle | P (forged) | – | P | – | – | P | P (reconcile) | – |
| 7 Stripe real Checkout/portal | – | – | E-1 | – | – | P (refused) | – | – |
| 8 SSO management/discovery/errors | P | – | P (F-4) | – | – | P | P | – |
| 9 SCIM (as IdP) | P (bad token) | – | P | P | – | P | P (rotate) | – |
| 10 org policies / MFA | – | – | P | P | P | – | – | – |
| 11 operator console | P (401) | – | – | – | – | P (403) | P | P |
| 12 MCP | P | – | P | – | – | P | – | – |
| 13 impersonation / export / RLS | – | – | P | – | P | P | P | P (refused write ops) · RLS – |
| 14 UI sweep (all pages, 3 widths, dark, back, keyboard, console) | – | – | P (F-8,C-1) | – | P | – | – | – |
| 15 migrations up/down with data, restart, perf | – | – | – | – | – | – | P | – |

## 5. Generated-project builds (via the real API: PUT spec → validate → preview → zip; venv Python 3.12, throwaway DB, `alembic upgrade head`, own pytest, uvicorn)
| Spec | Result |
|---|---|
| `library` (CRUD, 1-1/1-n/n-n/self relations, restricted ops) | validate ✔, 43 files, migrate ✔, own tests ✔, boots, /health /ready ✔, every collection: create/get/list/limit clamp/404/bad id/empty body/PATCH/DELETE ✔ (cascade delete verified) |
| `reserved_names` (my spec: entities Base, Session, Metadata, Class, Order, Group, Select, Table, User, Settings, Field, Depends, Request, Alembic, Health) | accepted, generated, migrate ✔, own tests ✔, boots, CRUD ✔ |
| `shop_auth` (auth + roles + custom fields, SMTP pointed to Mailpit) | tests 24 ✔; register/dup/custom-field+enum validation/weak pw, login blocked until verified, mailed token verify (single use), login, /me, refresh rotation + reuse refused, change password, magic link, password reset (single use), login rate limit ✔ (F-7) |
| `storage_payments` (auth+Stripe payments+S3 storage) | tests 233 passed/9 skipped ✔; roles enforced (customer cannot create order or read ops; admin can); anonymous 401; forged/garbage/stale webhook signatures rejected; real Stripe session creation blocked by E-1 (not a code defect); files endpoints require auth, S3 not stood up |
Hostile specs through the builder (J4.host.*, 40 cases): empty, duplicate entities/fields/relations, 11 reserved entity names, 10 reserved field names, Unicode/emoji names, SQL/path-traversal table/plural names, quote/triple-quote/code in defaults, enum injection, min>max, circular relations, unknown relation target, 1000 fields, 300 entities, 10k-char strings, 12 MB body, garbage/array bodies: **no 5xx; all cleanly accepted or refused; generation always finished**. Not executed: running the generated code of the injection-style defaults (only generation checked).

## 6. Checked and working (one line each)
- Sign-up validation (weak/oversized password, odd e-mails, NUL, HTML names) without 5xx; e-mail case-insensitive login; identical error for unknown user vs wrong password.
- Refresh cookie `HttpOnly; Secure; SameSite=strict; Path=/account`; refresh/logout need `X-Requested-With: builder`; logout invalidates refresh; logout-all kills other sessions; password change revokes old password.
- Per-IP auth rate limit with `Retry-After`; register burst limited.
- API tokens: scopes enforced, project pin, one-time display, revoke, unknown scope/empty/500-char name refused, quota 402 naming tokens.
- TOTP enrol/disable, recovery codes single-use, wrong code refused; org `require_mfa` needs owner MFA first, blocks MFA-less members from projects, API token cannot bypass.
- Org create/rename/slug rules, outsider 404, invitations (mail in Mailpit and in the real inbox → INBOX, link host correct), wrong-account accept refused, revoke/resend, role matrix (member/admin/owner), last-owner rules, ownership transfer, leave.
- Deletion: request → 423 locks, cancel, operator grace change and delete-now; org, projects and slug gone.
- Quotas: seats incl. pending invites, projects, API tokens, MCP tokens at n and n+1; races for last seat/last project exactly one winner; downgrade-over-limit blocks new items; operator overrides validated; SSO/SCIM/MCP plan flags enforced.
- Stripe webhooks: forged/stale/livemode/unknown/malformed events, checkout completed, upgrade by price id, duplicate and out-of-order events, customer mismatch, payment_failed → past_due (402 `subscription_past_due`, UI-ready), recovery, cancel → free, trial; reconcile runs; customers cannot call admin.
- SCIM: bearer auth, discovery docs, create/dup/foreign-domain, filters, pagination clamps, PUT/PATCH (incl. no-path replace), deactivate/reactivate/delete, group role mapping and revert, owner mapping allowed only for owners, rotate (owner and operator) invalidates old token, disable switch, audit entries, seat count.
- SSO management: discovery, login redirect, error redirects `sso_error=` for unknown org/IdP error/forged state/garbage ACS, domain validation (free-mail, malformed, claimed by another org), config validation (http URL, SSRF IPs, wrong protocol), check/test endpoints, deactivate/activate, plan-downgrade fallback.
- MCP: unauthenticated tools refused, pinned token cannot reach other project, scopes, REST token vs MCP, quota, downgrade and revoke stop access (J12.*; one expectation of mine was wrong: `initialize` is open, tools are guarded).
- Impersonation: consent switch, reason ≥5, read-only by default, blocked on tokens/password/MFA/members/export, banner endpoint, audit, operator end, ended token refused; per-org export has no secrets, member/outsider refused; support role cannot mutate.
- Operator console: every GET for admin/support, customers/anonymous refused, plan edit validation, temp password + forced change, revoke sessions.
- Migrations: downgrade `f2c8… → e7d3… → d1f5…` and upgrade back on a copy of the live DB, with data. `/health`, `/ready` OK; admin lists < 50 ms; 300 projects created in 2.4 s, `limit` clamped (422 above max); API log contains no tokens/keys.
- UI (owner, member): all 18 pages × 3 widths (+tablet subset, dark) render, no horizontal page scroll, no 5xx, no unexpected console errors, keyboard focus, back navigation; HTML in project names is escaped.

Artifacts: `journeys/` (API scripts), `ui/` (puppeteer), `fixtures/`, `evidence/` (redacted screenshots), `logs/`.
