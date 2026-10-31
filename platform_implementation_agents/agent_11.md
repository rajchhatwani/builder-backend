# Agent 11 report — claude-sonnet-5-5 — 2026-10-28

## Scope accepted
Queue row 11, Phase F (code): Postgres RLS behind a flag (off), impersonation (banner, per-org consent,
write-block, audit), per-org export, `docs/` (MULTITENANT_ARCHITECTURE, SSO_SETUP, SCIM_SETUP), pen test +
SOC 2 as **prep docs only**. Route walker and `review/tests` extended to every new route. Nothing committed;
no other branch touched; no Keycloak code touched; **RLS was not enabled anywhere** (only in throwaway test
databases). The branch is `phase_A_to_E` (the brief said `phase_A_to_B`); I only worked in the tree.

Baseline before changes: `tests/api tests/unit` → **2064 passed, 2 skipped** (the queue file still said 2047).

## What was already done
Rows 1–10 (see the earlier reports). Used here: `tests/api/_routes.py` (agent 10's repaired walker),
`ORG_ROUTE_ROLES`/`org_context`/`guard`, `audit_service.record`, org policies (agent 6), `require_admin`.

## Decisions (please review)
1. **RLS policy is "confine when scoped, open when unscoped".** `USING (app.organization_id unset OR
   organization_id = app.organization_id)`. Sign-in, SSO/SCIM callbacks, webhooks, the operator console
   and jobs span orgs and run unscoped exactly as today, so RLS can be rolled out without a flag day. It
   protects the org-scoped request paths, which is where a forgotten `WHERE organization_id` would leak.
   The plan's strict form (deny when unset) would need every platform path to declare itself; listed as a
   next step. If you want strict mode first, say so.
2. **Three separate switches** so nothing changes by accident: the migration only *creates* policies;
   `python -m app.core.rls enable --yes` turns RLS on (refuses without `--yes`); `BUILDER_RLS_ENABLED`
   makes requests bind the scope. I did none of the last two outside tests.
3. **Impersonation is DB-backed.** The 10-minute token only names an `impersonation_sessions` row; the
   row, the operator's role, the member's membership and the org's consent are re-read on every request,
   so ending a session or withdrawing consent works at once (and consent is re-checked even if the flag
   is flipped without the API clean-up — tested).
4. **A viewing token is one org, look-only on the org console, read-only on projects until the viewer
   switches writes on (5 minutes, audited).** Even then: no tokens, project auth secrets, export,
   billing, generate downloads, project create/delete, project-member changes; `/account/*` refuses it.
   `current_principal` now refuses viewing tokens unless the route is in `IMPERSONATION_OPEN_ROUTES`
   (default deny). Plan §4.5 only said "writes blocked unless a toggle"; the never-list is my addition.
5. **Export is owner-only, session-only, and also works while the org is locked for deletion** (data
   portability before the grace period ends). Plan §9 gave only the URL.
6. **Who can switch writes on:** the viewing tab (the operator) — it's the operator's explicit act, as §4.5 says.
7. `platform_audit_log.via` widened 10 → 20 so it can say `"impersonation"`; downgrade leaves it wide (the log
   is append-only, so rows cannot be shortened).

## Implementation summary
- **RLS** — `app/core/rls.py` (table lists, policy/enable/disable SQL, `status`, per-request `bind`/`release`,
  `after_begin` hook so a handler that commits stays confined, CLI). Migration `f2c8a4e6b1d9` (policies
  only, frozen table list). Wired in `guard` and `org_context` right after membership is proved;
  `SecurityMiddleware` clears the context at the end of every request (an in-process test client reuses
  the task). Covers `organizations`, every table with `organization_id`, the audit log (null-org rows
  stay visible/writable), and all project-child tables (visible iff their project is). Project transfer
  is the one flow that touches two orgs: it calls `rls.release`. Flag `rls_enabled` in `app/config.py`.
- **Impersonation** — migration `e7d3b9a1c5f2` (`organizations.allow_impersonation` default true,
  `impersonation_sessions`, audit `via` 20). `ImpersonationService`, `ImpersonationInfo` on `Principal`
  (`via="impersonation"`), `impersonation_denial` + `IMPERSONATION_OPEN_ROUTES` in `platform_authz`,
  `acting_principal`/`_check_impersonation` in `security.py`. Admin API (`impersonate:write`, platform
  admin only): `POST /admin/organizations/{org}/members/{user}/impersonate`, `GET
  /admin/impersonation/sessions`, `POST /admin/impersonation/sessions/{id}/end`. Viewer API: `GET
  /account/impersonation`, `POST …/writes`, `POST …/end` (`app/api/impersonation.py`). Org policy
  `allow_impersonation` in `GET|PATCH /orgs/{slug}/policies` and `allow_impersonation` on `AdminOrgRead`.
  `GET /orgs` and `GET /projects` are cut to the one org for a viewing token. Audit: `impersonation.started
  /request/denied/writes_enabled/writes_disabled/ended`, `project.change` carries `impersonator_id`; all
  carry the org id, so customers see them in their own audit tab.
- **Export** — `GET /orgs/{slug}/export` (`OrgExportService`): org + policies, plan, members, invitations,
  projects with assembled spec + members, SSO/SCIM status, org audit. No hashes, secrets, Stripe ids,
  certificates, project credentials. Audited `org.exported` (counts only).
- **Frontend** — `api/viewing.ts` (postMessage hand-off to a named tab; token never in a URL or storage),
  `ViewingBanner` (bottom bar: operator, countdown, Allow changes / Read-only, Exit), auth provider
  viewing mode (no refresh in that tab; "Viewing session ended" page), admin org detail: **View as** per
  member (reason dialog, disabled with the reason when the org withdrew consent, hidden for support) and a
  "Support sessions" table with End; Security tab: consent checkbox (confirm on turn-off) and owner-only
  **Download export**.
- **Docs** — `docs/MULTITENANT_ARCHITECTURE.md`, `docs/SSO_SETUP.md`, `docs/SCIM_SETUP.md` (customer
  facing), `docs/PENTEST_PLAN.md` and `docs/SOC2_EVIDENCE.md` (prep only; they state nothing was performed).

## Tests I wrote (TDD evidence)
Red first, then green, per unit.
- `tests/api/test_rls.py` (17): policies run as a **non-superuser** role (`rls_probe`); scoped sees own org
  only; children follow the project; audit; unscoped unconfined; cross-org INSERT refused; `SET LOCAL`
  dies with the transaction **and does not leak on a one-connection pool**; flag off = no-op; scope
  re-bound after commits; the app talking to Postgres as the policy-bound role still works and a
  handler that forgets its org filter still returns only the caller's org; project transfer under RLS
  (found and fixed a real break: it read a second org); **route walker**: every `/orgs/{slug}/…` route and
  every `/projects/{project_id}/…` route binds the scope; CLI refuses `enable` without `--yes`; policy
  lists cover every table with `organization_id` or a non-null `project_id`.
- `tests/api/test_impersonation.py` (45): start/consent/staff/non-member/reason, token never in audit or
  listings, read audit, writes off by default and the audited 5-minute switch (and its expiry), 20
  never-reach routes even with writes on, org confinement (`/orgs`, `/projects`), ending (viewer,
  operator), expiry, demoted operator, removed member, forged tokens (wrong member/operator/session),
  consent re-check without the API, operator org view shows consent, customer sees it in their audit.
- `tests/api/test_org_export.py` (8), `tests/api/test_operator_secrets.py` (3): **§7.1 walker** — plants
  a canary in every secret kind (project SMTP, OIDC secret, SCIM bearer, PAT, invitation token, TOTP
  secret, recovery code, password), then walks every `/admin` GET route, and every GET route a viewing
  token (writes on) can reach, and fails on any canary.
- `tests/api/test_access_matrix.py` (+4): Phase F routes exist and are guarded as designed; pure walk:
  no sensitive route is reachable with a viewing token; every org route is look-only; both resolvers bind
  RLS. `tests/api/test_migrations.py` (+1): policies installed, **RLS enabled nowhere**, round trip.
  `tests/api/test_org_policies.py`: expected policy body gains `allow_impersonation`.
- **Review scripts** (`review/`): `dump_routes.py` now records, per route, what a viewing token can do
  (`viewing`) and prints the reachable non-GET routes and the sensitive routes reachable (must be empty — it is).
  `review/artifacts/routes.json` regenerated (216 routes). New `review/tests/test_adv_phase_f.py` (6):
  recorded Phase F routes, viewing-token walk of every recorded route with writes on, forged tokens,
  token/canary grep across **every table**, generic sweep of all RLS tables as the policy-bound role,
  cross-org export. `mutate.py` +12 Phase F mutants (M22–M33).

## Test run result
- `uv run pytest tests/api tests/unit -q`: **2139 passed, 2 skipped** (baseline 2064 / 2; +75). The consent-recheck test
  was added after this run started; `tests/api/test_impersonation.py` re-run alone afterwards: 44 passed.
- `review/tests`: **99 passed, 2 failed** (was 93 / 2): the same two as agent 10 (F-007 support SSO check;
  `test_adv_prehijack::test_B…`). `dump_routes.py` was run (it rewrites `review/artifacts/routes.json`).
- Mutation (scratch copy): all 12 Phase F mutants M22–M33 **killed** (M22 first survived; the
  consent-recheck test was added to kill it).
- mypy: 10 errors, all pre-existing (none in new code). ruff: all new/changed files clean; remaining errors are pre-existing.
- `npx tsc -b` clean; `npm run lint` **57 warnings, 0 errors**; `npx vite build` OK.
- Alembic head `f2c8a4e6b1d9`. No new dependencies (backend or npm).

## Follow-up (owner's go-ahead, same day)
- **Daily digest built** (§4.5): `app/services/impersonation_digest.py`, job `python -m app.jobs.impersonation_digest`
  (`--dry-run/--force`, exit 0/1/2), webhook (Slack-compatible) and/or e-mail, once-a-day guard recorded as
  `impersonation.digest_sent`, preview `GET /admin/impersonation/digest`. Settings `BUILDER_SECURITY_DIGEST_*`.
  Tests: `tests/api/test_impersonation_digest.py` (10). Cron entry + destination still to be set per environment.
- **Local dev database:** started the compose Postgres (nothing was on 5432; old volume kept), ran `alembic
  upgrade head`, created role `builder_app` (no superuser/BYPASSRLS), wrote a git-ignored `.env`
  (app connects as `builder_app`, `BUILDER_RLS_ENABLED=true`), and ran `python -m app.core.rls enable --yes`
  there **only**. Smoke test against it: register two users, create project, owner 200, other user 404, export 200.
  Migrations/ops must still use the owner `builder` (`BUILDER_DATABASE_URL` override), the app role cannot alter tables.
- Decisions taken: permissive RLS kept; the unrelated formatting changes left as they are.

## Improvement scope — out of current phase
- Strict RLS (deny when unscoped, every platform path declares itself); `fields` and `platform_api_tokens`
  have no policy; no per-org encryption keys.
- The viewing hand-off was **not clicked through in a browser** (no browser run this session); it is
  type-checked, lint/build-clean, and the API side is fully tested. The postMessage hand-off, the banner
  and the pop-up-blocked path need a manual pass in Chrome.
- Real-IdP checks (Okta/Entra SCIM validators, real SAML/OIDC round trip) are still outstanding
  (`docs/PENTEST_PLAN.md` §8).
- No scheduler for the Stripe reconciliation or for sweeping expired impersonation rows (harmless: expired
  rows are inert).

## Open items / owner decisions
1. **Turning RLS on** anywhere (staging first, with a non-superuser app role) — the rollout steps are in
   `docs/MULTITENANT_ARCHITECTURE.md` §3. I did not and will not without a go-ahead.
2. Strict vs. permissive RLS (decision 1 above).
3. Is a viewing token allowed to switch writes on itself (current), or should that need a second operator?
4. **Unrelated files were reformatted by accident.** I ran `ruff format app` once and it reformatted 19
   files I had no reason to touch (`app/api/auth.py`, `app/api/mcp.py`, `app/core/generator/features/{auth,documents}/module.py`,
   `app/core/observability.py`, `app/core/validation_payments.py`, `app/models/{auth_config,auth_custom_field,project_role}.py`,
   `app/schemas/{auth_config,auth_custom_field,project_permission}.py`, `app/services/{api_token,auth_config,auth_custom_field,auth_secrets,generation,project_permission,project_role}_service.py`).
   The tree was clean when I started, so `git checkout -- <those files>` restores them; the auto-mode
   classifier blocked me from running it, so they are still modified (formatting only, +92/−200 lines).
   Files I changed on purpose were checked: their diffs are only my edits.
5. Existing-but-unchanged: `review/tests/test_adv_admin.py::test_support_is_read_only_everywhere` (F-007) and
   `test_adv_prehijack::test_B…` still fail for the reasons agent 10 gave.

## HANDOFF: continue at the owner — Phase F code is done (rows 1–11 ticked); decide the open items above, then run the manual browser pass for "view as" and, only with approval, the RLS rollout in `docs/MULTITENANT_ARCHITECTURE.md` §3

---

## Detailed log of the follow-up session, with intent

### A. Local dev database with RLS actually on
**Intent:** the owner asked for RLS to be switched on in development. A policy only bites for a role that is
neither superuser nor `BYPASSRLS`, and the compose database user `builder` is a superuser, so enabling RLS while
the app still connected as `builder` would have changed nothing and looked like success. So the app needed a
restricted role of its own.

Steps, in order (all against the local compose database only):
1. `ss -ltnp | grep :5432` and `docker ps -a`: nothing listening; only stopped containers (`builder-backend-postgres-1`,
   an old `blog-app-db-1`). Nothing killed. The existing `postgres_data` volume was reused so earlier dev data survives.
2. `docker compose up -d postgres`, waited for `pg_isready`.
3. `BUILDER_DATABASE_URL=…builder:builder@localhost… uv run alembic upgrade head` (owner role, because migrations
   need DDL rights). Applied the earlier pending migrations plus `e7d3b9a1c5f2` and `f2c8a4e6b1d9` (all additive).
4. Created `builder_app` (`LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE`), granted CONNECT, USAGE on the
   schema, SELECT/INSERT/UPDATE/DELETE on all tables, USAGE/SELECT on sequences, and `ALTER DEFAULT PRIVILEGES`
   so tables created by later migrations are usable without a new grant. It owns nothing, so it cannot alter or
   drop tables or policies.
5. Wrote `.env` (git-ignored): `BUILDER_ENVIRONMENT=local`, `BUILDER_DATABASE_URL` as `builder_app`,
   `BUILDER_RLS_ENABLED=true`.
6. `python -m app.core.rls enable --yes` (58 statements: ENABLE + FORCE on 29 tables). `status` confirmed policy/on/forced.
7. Smoke test with the real API as `builder_app`: two sign-ups, a project, owner GET 200, other user GET 404,
   `/orgs/{slug}/export` 200, no errors in the server log. Server stopped afterwards.

**Side effect found and fixed:** `Settings` reads `.env`, so the new file would have turned RLS binding on inside the
test suite (two tests that assert "off by default" would fail, and every test would run with the hook installed).
Added autouse fixture `_no_dev_rls` in `tests/api/conftest.py` (sets `BUILDER_RLS_ENABLED=false`, clears the settings
cache); tests that need it on set it themselves. Confirmed: the two failing tests pass again.

**To undo:** `python -m app.core.rls disable` (instant, no data change) and/or remove `BUILDER_RLS_ENABLED` from `.env`.
**To reproduce on a fresh machine:** steps 2–6; the role SQL is in this section.

### B. Daily support-access digest
**Intent:** plan §4.5 asks for a daily digest of impersonation to a security channel. The point is detection: a
person on the security side sees all staff viewing of customer orgs without having to go looking, and silence is
itself a signal.

Design choices and why (industry-standard options, chosen without asking as instructed):
- **Separate job, not an in-process scheduler.** The API runs with several workers; an in-process timer would send
  duplicates. `python -m app.jobs.impersonation_digest` is run by cron / a systemd timer / a Kubernetes CronJob,
  whose own monitoring then covers "the job did not run". Exit codes 0 / 1 (no destination) / 2 (delivery failed)
  let the scheduler alert.
- **Slack-compatible webhook plus optional e-mail.** Webhook = `POST {"text": …}` (works for Slack and most chat
  tools); e-mail reuses the existing SMTP code. No new dependency (`httpx` was already used for Stripe).
- **Always sends, even with no sessions** ("No support access in this period"), so a missing message means a broken
  job, not a quiet day.
- **Idempotent:** a successful send writes `impersonation.digest_sent` (counts and channel names only); a second run
  within 90 % of the window is skipped unless `--force`. A failed delivery writes nothing, so it can be retried at once.
- **Secret handling:** the webhook URL is a `SecretStr`, never logged, never in audit detail (tested).
- **Content:** per session: operator, viewed-as, org, reason, start, end/expiry, read-only vs writes on, count of
  changes made; plus how many attempts were refused because an org had turned support access off. Built from
  `impersonation_sessions` and the audit log (`impersonation.writes_enabled`, `project.change` with the
  impersonator id, `impersonation.denied` with `why=org_policy`).
- **Preview:** `GET /admin/impersonation/digest?hours=24` (platform admin only, support gets 403) so an operator can
  see the text without sending it; added to the route-walker list in `test_access_matrix.py`.

Files: `app/services/impersonation_digest.py`, `app/jobs/impersonation_digest.py`, `app/jobs/__init__.py`,
`ImpersonationDigestRead` in `app/schemas/account.py`, route in `app/api/admin.py`, settings
`security_digest_webhook_url` / `security_digest_email` / `security_digest_hours` in `app/config.py`.
Tests (`tests/api/test_impersonation_digest.py`, 10): content with who/why/changes/refusals, quiet day, window
bounds, webhook post + audit without URL, once-a-day guard and `--force`, e-mail channel, failed delivery not
recorded as sent, no-destination reported, operator preview, support refused. Red first (module missing), then green.
CLI checked by hand: `--dry-run` prints; no destination → exit 1.

**Not done / needs the owner:** a destination (webhook URL or address) and a schedule per environment, e.g.
`0 7 * * * cd /app && python -m app.jobs.impersonation_digest`.

### C. Items the owner decided
1. RLS stays permissive when unscoped. 2. RLS enabled in dev (section A); not anywhere else.
3. The 19 accidentally reformatted files are accepted as-is (formatting only; development phase).

### D. Digest screen and the headless-Chrome click-through (owner asked for both)
**Digest screen:** `SupportDigest` on the admin Organizations page (platform admins only; hidden for support):
period selector (24 h / 3 d / 7 d) showing the text the scheduled job would send; sends nothing.
(`api/types.ts`, `api/client.ts` `adminImpersonationDigest`, `pages/admin/AdminPages.tsx`.)

**Click-through:** headless Chrome 156 via puppeteer-core, installed in the session scratchpad (not in the repo; no new
repo dependency), against the real stack: API as the restricted `builder_app` role with RLS enabled and bound,
Vite dev server, seeded org `viewco`, a platform admin with TOTP. **27/27 checks pass** (final run), covering:
operator sign-in with TOTP; digest preview; "View as" dialog (reason required, text); hand-off to a new tab; banner
(viewed member, org, operator, read-only, countdown); token not in the URL or in web storage; write refused while
read-only (403); banner "Allow changes" → write allowed (201), tokens route still 403 with writes on; back to
read-only; project opens inside the viewing tab; operator sees the active session; **reload of the viewing tab →
"Viewing session ended"** (no login screen, no silent switch to another identity); Exit closes the tab and the
operator's list shows it ended; owner turns consent off (confirm dialog) and downloads the export; the operator's
"View as" is then disabled with the reason shown; **pop-up blocked** (simulated by `window.open → null`, as browsers do)
→ message shown and the just-created session is ended, not left running.

**Real bugs found by the click-through and fixed:**
1. Reloading a viewing tab waited 15 s for a hand-off that never comes. Now ends at once (a non-secret
   `sessionStorage` flag per tab).
2. A second "View as" would have reused the first tab by name and never delivered its token. Each session now opens
   its own uniquely named tab (`builder-viewing-<uuid>`).
Noted, not changed: the viewed member's UI still shows buttons like "Delete" on project cards; the server refuses them
while read-only, but they could be hidden in viewing mode (cosmetic).

**Environment findings (dev only):**
- With `SECRET_KEY` unset, local mode generates a new key on every API start, and TOTP secrets are encrypted with it, so
  a restart makes every enrolled authenticator unreadable. Added a stable `SECRET_KEY` to the git-ignored `.env`;
  re-enrolled the test operator. Existing dev accounts enrolled under earlier random keys (e.g. `admin@dumbpotato.com`)
  were never recoverable by restart either; reset TOTP for them if needed.
- The sign-in rate limiter (30 per 5 min per IP, in-process) is hit by repeated automated runs; restart the API to reset.
- Created dev logins (password `correct-horse-battery-staple`): `ops@view.test` (platform admin, TOTP secret in the
  scratchpad `seed.json`), `owner@view.test`, `bob@view.test`; org `viewco`. Delete them if you don't want them.
Servers started for the test were stopped afterwards; the Postgres container is still running (RLS on).
Gates after this work: `tsc` clean, `npm run lint` 57 warnings / 0 errors, `vite build` OK.
