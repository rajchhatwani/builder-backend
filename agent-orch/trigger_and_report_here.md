# Agent Orchestration — Trigger & Handoff Log

> **This file is the orchestration baton.** When you (an agent) start a session, read this
> file first, then read `/mnt/files/projects/builder-backend/platform_implementation_agents/`
> for the latest numbered agent report (`agent_1.md`, `agent_2.md`, …). Then open the plan
> at `PLATFORM_SAAS_PLAN.md` and continue from the next **unfinished** phase/step.

## Mission (do not re-plan)

Implement `PLATFORM_SAAS_PLAN.md` end-to-end, in phase order **A → F**:

- Phase A — Organizations core (migration + models + service + /orgs API + admin ext + UI)
- Phase B — Plan enforcement & seat accounting
- Phase C — Stripe automation
- Phase D — Enterprise SSO (SAML + OIDC per org)
- Phase E — SCIM 2.0
- Phase F — Hardening (RLS, pen test, impersonation, SOC 2 evidence)

The plan is authoritative. Do **not** redesign. Do **not** second-guess the schema in §3,
roles in §2.2, or quota approach in §6. If you find a genuine issue, write it in your agent
report under "Improvement scope — out of current phase" instead of silently diverging.

## The TDD cycle every agent follows

Red → Green → Refactor, **per unit**:

1. Pick the next step in the current phase.
2. Write a failing test that would pass only when the step is implemented
   (`tests/api/test_*.py` is the primary location; add `tests/unit/*.py` for pure services).
3. Implement the smallest change that makes the test pass.
4. Repeat for the next unit of behavior.
5. When finishing a phase: rerun the entire test suite (`uv run pytest -q`) and confirm
   zero regressions before writing your handoff.

## Code conventions in this repo

- Python 3.12, FastAPI, SQLAlchemy 2 async, Pydantic v2, Alembic.
- Services raise `AppError(code, message, status_code)`; FastAPI handlers translate.
- `AsyncSession` is injected via `Depends(get_session)`.
- Models live in `app/models/`, schemas in `app/schemas/`, services in `app/services/`,
  routes in `app/api/`.
- Every write-path mutates audit via `app.services.audit_service.record`. **Never log raw
  tokens, passwords, or spec content.** Audit `detail` sanitizer strips keys matching
  password/token/secret/authorization/cookie/otp.
- Alembic revision IDs are 12-char hex. Chain `down_revision` to the previous head.
- Tests use `conftest.py` fixtures: `client`, `client_for`, `make_user`, `anon_client`.
  Postgres is spun up by testcontainers unless `TEST_DATABASE_URL` is set.
- Run tests with `uv run pytest -q` from repo root. Fast mode shaves cost: scrypt N is
  lowered automatically in the autouse fixture.

## Current status

### Agent 1 — DONE (Phase A). Report: `platform_implementation_agents/agent_1.md`
### Agent 2 — DONE (Phase B). Report: `platform_implementation_agents/agent_2.md`

### Agent 3 — DONE (Phase C). Report: `platform_implementation_agents/agent_3.md`
### Agent 8 — DONE (Phase E backend). Report: `platform_implementation_agents/agent_8.md`
### Agent 9 — DONE (Phase E frontend). Report: `platform_implementation_agents/agent_9.md`
### Agent 10 — DONE (review fixes). Report: `platform_implementation_agents/agent_10.md`

## Work queue — the FIRST unchecked row is yours

| Agent | Scope | Plan sections | Done |
|-------|-------|---------------|------|
| 1 | Phase A — organizations core (backend) | §3, §12.A | [x] |
| 2 | Phase B — plan enforcement + Stripe Checkout | §6, §12.B | [x] |
| 3 | Phase C — Stripe automation (webhooks, seat sync, past_due) | §6.3, §10, §12.C | [x] |
| 4 | **Frontend leftovers A–C** (see "Row 4 details" below) — no new backend features | §7, §8, §8.1 | [x] |
| 4b | **Backend gaps A–C** — every item in `agent-orch/backend_gaps_phase_A_to_C.md` (done by agent 2, report `agent_2b.md`; 4 owner decisions left open there) | gaps file | [x] |
| 4c | **Owner decisions round 1** — team orgs start on `free`; org deletion = request + grace period (done by agent 2, see `agent_2b.md` "Round 2") | owner answers | [x] |
| 4d | **Frontend for rows 4b + 4c** (agent 4, second pass — report `agent_4b.md`). See "Row 4d details" below | §7, §8 | [x] |
| 5 | **First:** the two small open P2 items at the bottom of `agent-orch/backend_gaps_phase_A_to_C.md` (423 details need the org slug; `GET /projects` lists locked orgs' projects). Then Phase D.1–D.4 — SSO backend: migration, DNS domain verification, SAML + OIDC adapters, SP metadata, JIT provisioning, `allow_sso` gate (done by agent 5, report `agent_5.md`) | §4.2, §6.2, §12.D | [x] |
| 6 | **Backend** for Phase D.5–D.7 (agent 6, report `agent_6.md`; the owner moved the UI to row 7): "test with my own email" SSO flow, operator SSO status + config check, per-org MFA policy, **built-in TOTP for platform users + mandatory MFA for platform admins (§4.4 Phase 1)**, per-org session-TTL policy (§8 Security policies) | §4.2, §4.4, §8, §12.D | [x] |
| 7 | **Frontend for rows 5 + 6 + sync audit** (agent 7, frontend-only): SSO settings page `#/org/<slug>/sso`, login-page discovery + `#/sso/complete` + `sso_error`, MFA enrolment/login/recovery codes, admin MFA enrolment at sign-in, `#/org/<slug>/policies`, operator SSO status/check, People 2FA column — plus every item in `agent-orch/frontend_gaps_phase_A_to_D.md` (done by agent 7, report `agent_7.md`) | §4.2, §4.4, §7, §8, §8.1 | [x] |
| 8 | **Backend** for Phase E — SCIM 2.0 (agent 8, report `agent_8.md`; the owner moved the UI to row 9): migration, `/scim/v2` Users/Groups/discovery, group → role mapping, bearer issue/rotation, offboarding, operator status + rotation | §4.3, §12.E | [x] |
| 9 | **Frontend for row 8** (frontend-only): SCIM section on `#/org/<slug>/sso`, operator SCIM column + Rotate SCIM token, `scim.` audit filter — everything in `agent-orch/frontend_scim_phase_E.md` (done by agent 9, report `agent_9.md`) | §4.3, §7, §8, §12.E.4–5 | [x] |
| 10 | **Review fixes** (agent 10, report `agent_10.md`): findings F-001…F-017 from `review/review_PLATFORM_SAAS_PLAN.md`, test-first, in the review's §8 order | review §3, §8 | [x] |
| 11 | Phase F (code) — Postgres RLS behind a flag, impersonation, per-org export, `docs/` (MULTITENANT_ARCHITECTURE, SSO_SETUP, SCIM_SETUP). Pen test + SOC 2: prep docs only. Make the RLS tests part of the repaired route walker (`tests/api/_routes.py`) | §3.3, §4.5, §9, §11, §12.F | [ ] |

Rules for the queue:
- Take **only** the first unchecked row. Never start while another agent's report lacks its
  final `HANDOFF:` line — two agents in one tree overwrite each other.
- When done: tick your row, add a line under "Previous handoffs", and end your report with
  `HANDOFF: continue at row <N+1> — <scope>`.
- Row too big? Finish a clean sub-part, insert a new row right below yours for the rest, then
  hand off.
- Anything needing the owner's decision (new dependency, turning RLS on in prod, plan pricing):
  ask, or write it under "Open items" — don't decide silently.

### Row 4 details — frontend leftovers (backend already exists)
Build in `frontend/src`, matching existing style (plain React, existing CSS classes, `Modal`
with `form > header / div / footer`). No new npm dependencies without noting them.
1. Org console at `#/org/<slug>` with tabs People, Invites, Projects, Plan. Plan =
   `pages/OrgPlanPage.tsx` (exists, already has Phase C "Manage billing"); currently
   `App.tsx` routes every `#/org/...` to it (`page: 'org-plan'`).
   - People: members + roles; admins change role / remove; owners transfer ownership and
     delete a team org.
   - Invites: pending list, invite by email + role, revoke; show the token/link once.
   - Projects: org projects, linking to `#/p/<id>`.
   - Non-admins: read-only + "ask your admin" message on admin-only panels (§8).
2. Create team org + org switcher in the sidebar (sidebar already lists orgs under "Plan & usage").
3. Accept-invitation UI: `GET /orgs/invitations/pending`, `POST /orgs/invitations/accept`.
4. Org breadcrumb on the project workspace (§8.1).
5. Admin console: Plans tab (`GET /admin/plans`, `PUT /admin/plans/{id}`) and an org detail
   view with plan change (`PATCH /admin/organizations/{id}/plan`). The Organizations tab with
   seat/project overrides exists in `pages/admin/AdminPages.tsx`.
6. Any Phase C UI agent 3 listed as missing in `agent_3.md`.
Endpoints: docstring at the top of `app/api/orgs.py`, plus `app/api/admin.py` and
`app/api/billing.py`. Any 402 already opens `components/QuotaPrompt.tsx`.
Gate before handoff: `npx tsc -b`, `npm run lint` (no new warnings in your files),
`npx vite build` in `frontend/`, and the backend suite stays green.

### Row 4d details — frontend for rows 4b + 4c (backend is done; no backend changes)
Most of row 4b's UI was already switched over by agent 2 (see `agent_2b.md` "Frontend"). Check
it in a browser and finish what's left:
1. **Org deletion request** (row 4c). `DELETE /orgs/{slug}` now returns **202** + the org with
   `deletion_scheduled_for` (it no longer deletes at once). Update the OrgConsole "Delete
   organization" confirm text: the org is locked now, deleted with **all its projects** on
   that date, and can be revoked until then.
   - When `Organization.deletion_scheduled_for` is set: show a locked banner on the org console
     ("Scheduled for deletion on <date>"), an owner-only **Cancel deletion** button
     (`POST /orgs/{slug}/deletion/cancel`), and hide/disable the tabs (their API calls answer
     **423** `org_deletion_pending`). Mark the org as locked in the sidebar list.
   - Any **423 `org_deletion_pending`** response (project pages too): show a clear "this
     organization is scheduled for deletion" message with a link to the org page — add a
     global handler next to the 402 one in `api/client.ts`.
2. **Admin console**: on the org detail and Organizations list show `deletion_scheduled_for`;
   on the detail page for a pending request add **Change period** (`PATCH
   /admin/organizations/{id}/deletion {grace_days, reason}`) and **Delete now** (`POST
   /admin/organizations/{id}/deletion/execute {reason}`, danger confirm).
3. **Team orgs start on `free`** (row 4c): after "Create organization", tell the creator the
   org is on the Free plan (1 seat) and link to its Plan tab to upgrade; invites will 402 until
   then (the 402 prompt already exists).
4. Verify row 4b's switched-over screens in a browser (invite accept/resend/e-mail state, org
   Projects actions, Audit tab, admin Billing/Insights/org detail) and fix anything broken.
Gate: `npx tsc -b`, `npm run lint` (no new warnings), `npx vite build`; backend suite stays at
**1751 passed**. Write `platform_implementation_agents/agent_4b.md` (don't overwrite
`agent_4.md`), tick row 4d, add a "Previous handoffs" line, hand off to row 5.

### Row 7 details — frontend for rows 5 + 6 (backend is done; no backend changes)
The full, prioritised list with every endpoint, field and error code is in
**`agent-orch/frontend_gaps_phase_A_to_D.md`** (written by agent 6 from an OpenAPI-vs-`client.ts`
audit). Do the **P0** items first: `/admin/login` and `/account/login` can now answer an MFA
challenge instead of a session, so the admin console can't sign in until the challenge / enrolment
steps exist (local workaround: `BUILDER_ADMIN_MFA_REQUIRED=false`). Then P1 (account 2FA, org
`sso` + `policies` tabs, 403 `org_mfa_required` prompt, admin SSO column / check / MFA reset), then
P2. Match the existing style (plain React, existing CSS classes, `Modal`). A QR-code library would be
the first new npm dependency, so note it (or show the secret for manual entry instead).
Gate: `npx tsc -b`, `npm run lint` (no new warnings over the existing 57), `npx vite build`; the
backend suite stays green. Write `platform_implementation_agents/agent_7.md`, tick row 7, and hand
off to row 8 (SCIM).

### Every agent — startup checklist
1. Read this whole file; your scope is your queue row.
2. Read every `platform_implementation_agents/agent_*.md` in order — especially the previous
   agent's HANDOFF, "Open items" and "Improvement scope".
3. Read the plan sections listed in your row.
4. Run `uv run pytest tests/api tests/unit -q` and confirm green (currently **2047 passed,
   2 skipped**). Skip `tests/e2e` — it needs the Docker Compose stack and hangs without it.
5. Work test-first; write `platform_implementation_agents/agent_<N>.md` as you go.

### Conventions learned so far
- Alembic head is `d1f5a7c3e9b2` (row 10: `sso_connections.trust_unverified_email`; before it `c8a4e6b2d9f1`, project members backfilled into their org). Previous: `b3d7f1a9c5e2`
  (`email_verified_at`), `a9c4e2f7b1d3` (row 8: SCIM directories/users/groups), then `f5c3a8e1b7d9`
  (row 6: MFA + security policies + SSO test results),
  `e4b9c2d7a1f5` (row 5: SSO), `d8f2a4b6c1e3` (row 4c: org deletion requests).
- Platform staff always sign in with TOTP (`BUILDER_ADMIN_MFA_REQUIRED`, default true): `/admin/login`
  answers an MFA challenge, not a session. Tests sign staff in with `tests/api/_mfa_helpers.py`
  (`admin_sign_in`, `enroll`) and the `totp_clock` fixture; `bearer_for(user, amr=["pwd","otp"])`
  mints an MFA'd session token directly.
- Org MFA policy (`require_mfa`) is enforced in `org_context`, `guard` and MCP; new org routes that
  must stay reachable without MFA go in `platform_authz.ORG_ROUTES_OPEN_WITHOUT_MFA`.
- `tests/api/conftest.py::_unlimited_personal_plan` puts test users' personal orgs on the
  uncapped `enterprise` plan; quota/billing tests set the plan they need explicitly.
- Stripe is always faked in tests (monkeypatch `app.services.stripe_client.*`); no Stripe SDK,
  plain `httpx`.
- Quota/feature refusals go through `OrganizationService._deny` → 402 + `quota.denied` audit.
- Unauthenticated routes must be added to `PUBLIC` in `tests/api/test_access_matrix.py`.
- Every `/orgs/{slug}/…` route must use `Depends(org_context)` and be listed in
  `platform_authz.ORG_ROUTE_ROLES` (a test walks the routes; unlisted = refused).
- A project member must belong to the project's org (`not_an_org_member`). Tests that share a
  project call `tests.api.conftest.add_to_project_org(project_id, email)` first.
- Projects always have an org (NOT NULL). Pre-accounts projects live in the holding org
  `unclaimed-projects` until the bootstrap admin adopts them.
- SCIM routes (`/scim/v2/...`) authenticate with the org's SCIM bearer (`app.api.scim.scim_auth`);
  the access-matrix walker accepts that dependency. SCIM errors are `ScimError` → SCIM error JSON.
- Agent 3's handoff notes for Phase D (allow_sso gate, `app.core.crypto` for client secrets,
  never audit IdP certs/secrets) apply to row 5 — read them in `agent_3.md`.

### Agent report format (`agent_<N>.md`)

```
# Agent <N> report — <model id> — <ISO timestamp>

## Scope accepted
<which phase/steps I owned when I started>

## What was already done
<bullet list of code/tests landed by prior agents, cross-referenced to files>

## Research notes
<external patterns I checked, decisions I confirmed from the plan>

## Implementation summary
<file-by-file what I changed, with brief motivation; focus on surprises>

## Tests I wrote (TDD evidence)
<paths of test files and what they cover>

## Test run result
<paste the final `pytest -q` summary line and anything red/flaky>

## Improvement scope — out of current phase
<things I noticed but DID NOT change because they belong to a later phase or a different concern>

## Open items / known issues
<anything I know is still broken and why>

## HANDOFF: continue at <phase.step> — read <file(s)> first
```

## Do and don't

- **Do** keep every commit test-first. **Do** run `uv run pytest -q` before writing handoff.
- **Do** make backfill migrations idempotent and reversible where possible.
- **Don't** change the Keycloak code (that's the generated-project auth, not Builder auth).
- **Don't** introduce new dependencies without noting them in your agent report.
- **Don't** delete prior agent reports.
- **Don't** touch other branches or push remotes. Operate on `need_review_before_merge` and
  commit when the user asks — otherwise leave work in the working tree.

## Previous handoffs (append below as agents finish)

- **Agent 1 → Agent 2** (2026-10-26, opus-4.7): Phase A backend complete (orgs, members,
  invites, plans, subscriptions, admin ext). 1617 tests green. Phase A step 6 (frontend
  UI) deferred to a frontend slot; Phase B is the next phase in order.
- **Agent 2 → Agent 3** (2026-10-26, opus-5-5): Phase B (locked quota checks + `quota.denied` audit at
  every §6.2 point, accept-time seat re-check, API/MCP token caps per org, Stripe Checkout
  endpoint without webhooks, Plan & usage page, global 402 upgrade prompt, admin Organizations
  tab with seat/project overrides) — 1642 passed. → Phase C.1.
- **Agent 3 → Agent 4** (2026-10-26, opus-5-5): Phase C (signed Stripe webhook at
  `POST /billing/stripe/webhook` syncing plan/status/period/ids — idempotent, order-safe, customer-
  and replaced-subscription-guarded; one subscription per org via 409 on second Checkout + Billing
  Portal endpoint; high-water-mark seat sync on invite accept, reset at renewal; `past_due` blocks
  new seats/projects with 402 `subscription_past_due`; "Manage billing" UI) — 1689 passed. → Phase D.1.
- **Queue set up** (2026-10-26, by agent 2 at the owner's request): agent 3 had pointed agent 4 at
  Phase D; re-routed so agent 4 builds the missing frontend (row 4) first and Phase D starts at
  agent 5. See "Work queue".
- **Agent 4 → Agent 5** (2026-10-26, opus-5-5): Row 4 frontend (org console `#/org/<slug>` with
  People / Invites / Projects / Plan tabs + "ask your admin" for members, create org + sidebar org
  switcher, `#/invitations` + `#/invite/<token>` accept flow, org breadcrumb in the project
  workspace, admin Plans tab + org detail with plan change and audit tail). No backend changes.
  Backend gaps found against the plan are in **`agent-orch/backend_gaps_phase_A_to_C.md`** (for the
  owner to hand back to earlier agents). Suite unchanged: 1689 passed. → Row 5 (Phase D.1).
- **Agent 2 → row 5** (2026-10-26, opus-5-5, row 4b): all backend gaps A–C closed except 4 owner
  decisions (grandfathering, team-org start plan, per-seat price, free-plan numbers): org-role
  route table + `org_context`, owner-only rules, project↔org membership, NOT NULL migration,
  safe org delete, invite accept-by-id/resend/e-mail, project create/join/move per org, org
  audit, admin org detail/Billing/Insights, trial expiry, Stripe reconciliation, livemode check;
  frontend switched over — 1739 passed. → row 5 (Phase D.1).
- **Agent 2 → row 4d** (2026-10-26, opus-5-5, row 4c): owner decisions — team orgs start on
  `free`; org deletion is a request (locked at once, owner can revoke, default 7-day grace
  period, operator can change it or delete early, then org + projects deleted by
  `org_deletion_service`). 1751 passed. → row 4d (frontend, agent 4).
- **Agent 4 → Agent 5** (2026-10-26, opus-5-5, row 4d): frontend for rows 4b + 4c — org deletion
  request (new confirm text, locked org console with owner-only Cancel deletion, global 423
  `org_deletion_pending` prompt, locked badge in the sidebar, locked project cards on the Projects
  page, 423 message in the workspace), admin deletion badge + Change period / Delete now, Free-plan
  notice and toast for new team orgs. Row 4b screens contract-checked against the OpenAPI schema
  (all routes, params, bodies and 12 response types match); **not clicked through in a browser**.
  Two new backend gaps added to `backend_gaps_phase_A_to_C.md` ("Round 2"). No backend changes —
  1751 passed. Report: `agent_4b.md`. → Row 5 (Phase D.1), agent 5.
- **Agent 5 → Agent 6** (2026-10-27, opus-5-5, row 5): Round 2 gaps (the 423 names the org;
  `GET /projects` flags locked orgs, and the UI uses both). Phase D.1–D.4 SSO backend: migration
  `e4b9c2d7a1f5`; SAML (signxml) + OIDC (PKCE, JWKS) adapters; SP metadata; DNS TXT domain
  verification; `POST /account/login/discover`; JIT with a role setting and seat check;
  `allow_sso` 402. The org's IdP may only sign in addresses on its verified domains, never staff;
  login state is single-use and browser-bound; private IdP URLs are refused (SSRF). New deps:
  signxml (+lxml), dnspython, pyjwt. 1847 passed. → Row 6 (Phase D.5–D.7), agent 6.
- **Agent 6 → Agent 7** (2026-10-27, opus-5-5, row 6 — backend only; the owner moved the UI to a new
  row 7): built-in TOTP (RFC 6238, no new dependency) with recovery codes, an MFA challenge step on
  `/account/login` and `/admin/login`, mandatory MFA for all platform staff (enrolment at sign-in,
  refresh refuses non-MFA staff families), operator MFA reset; `amr` on every session; org policies
  `GET|PATCH /orgs/{slug}/policies` (require MFA — enforced on org routes, project routes and MCP;
  absolute session-TTL cap, strictest org wins); SSO "test with my own e-mail" (works before
  activation, never signs in), `…/sso/check` for admins and operators, SSO status on the admin org
  list, 2FA on member lists; closed MCP's missing org checks. Migration `f5c3a8e1b7d9` = new head.
  **The current admin UI cannot sign in until row 7 P0 ships** (`BUILDER_ADMIN_MFA_REQUIRED=false`
  locally). Frontend audit → `agent-orch/frontend_gaps_phase_A_to_D.md`. 1916 passed.
  → Row 7 (frontend), agent 7.
- **Agent 7 → Agent 8** (2026-10-27, opus-5-5, row 7 — frontend only): every item in
  `frontend_gaps_phase_A_to_D.md`. Second sign-in step on `/account/login` and `/admin/login` (code
  or recovery code; staff set up TOTP at sign-in, recovery codes shown once) — **the admin console
  signs in again**. Email-first login with SSO discovery, `#/sso/complete`, `sso_error` messages.
  Account → Two-factor (on/off, new codes). Global 403 `org_mfa_required` prompt plus "Needs 2FA"
  project cards. Org console SSO tab (domains + TXT, SAML/OIDC form, test, check, on/off) and
  Security tab (require 2FA, session length); People 2FA column. Admin: SSO column, Check SSO, 2FA
  columns, Reset 2FA, audit org filter. QR code on TOTP setup, added at the owner's request: **new
  dependency `qrcode` (+ `@types/qrcode`)**, lazy-loaded as its own chunk. Clicked through in
  headless Chrome against a throwaway stack (42 checks); the real IdP round trip is only
  type-checked. No backend changes — 1916 passed. Notes for agent 8 (SCIM building blocks, reuse
  points) are in `agent_7.md`. → Row 8 (Phase E SCIM).
- **Agent 8 → Agent 9** (2026-10-27, opus-5-5, row 8 — backend only; at the owner's request the SCIM UI
  is the new row 9 and Phase F is row 10): SCIM 2.0 at `/scim/v2` (Users + Groups CRUD, filters,
  PATCH in Okta/Entra shapes, ServiceProviderConfig/ResourceTypes/Schemas), tenant from a hashed
  `bb_scim_` bearer shown once; provisioning only on the org's verified domains (never staff),
  existing accounts linked, new ones SSO-only; seat-checked + Stripe seat sync; offboarding removes
  the org + its project memberships, revokes this org's pinned tokens and signs out everywhere,
  hands solely-owned projects to an org owner, never removes/demotes the last owner; group → role
  dictionary (owner mappings by owners only); `allow_scim` 402; operator SCIM column + token
  rotation that nobody sees. Migration `a9c4e2f7b1d3` = new head. No new dependencies.
  1978 passed. UI spec → `agent-orch/frontend_scim_phase_E.md`. → Row 9 (SCIM frontend).
- **Agent 9 → Agent 10** (2026-10-27, opus-5-5, row 9, frontend only): SCIM UI from
  `frontend_scim_phase_E.md`.
  - Org tab renamed "SSO & SCIM", with a SCIM section: status, last sync and counts; Generate /
    Rotate token, shown once inline with an "I saved it" gate and never stored; on/off; Remove;
    setup checklist + Base/Users URL; group → role editor (Owner hidden for admins, read-only when an
    Owner mapping exists); plan notice.
  - 402 prompt: `scim` label + "not in this plan" wording. People help line. "SCIM" as the actor in
    both audit views.
  - Admin: SCIM column, org-detail status + **Rotate SCIM token** (reason, §7.1 wording, hidden for
    support), `scim.` / `scim` audit filters.
  - Found: after an operator rotation, a new token left SCIM off. Agent 8 decided it wasn't intended
    and fixed `ScimService.issue_token`: a fresh token after an operator rotation switches SCIM back
    on, and an admin's own "off" still stays off. Banner and rotate-dialog text updated to match.
  - Clicked through in headless Chrome against a throwaway stack (63 checks). No new dependencies,
    no backend changes — 1978 passed. → Row 10 (Phase F).
- **Agent 10 → row 11** (2026-10-27, sonnet-5-5, row 10 — review fixes): F-005 (unverified accounts
  are reset when an IdP links them; invite-by-id needs a verified address), F-002 (session-only org
  actions), F-001 (route walker `tests/api/_routes.py`), F-014, F-003, F-013, F-012 (migration
  `c8a4e6b2d9f1`), F-009, F-008 operator domain release, F-004/006/010/011/015. Skipped with reasons:
  F-007, F-008 re-check, sign-up e-mail verification, rest of F-016. 2047 passed. → Row 11 (Phase F).
