# Agent 2 (second pass, queue row 4b) report — claude-opus-5-5 — 2026-10-26

## Scope accepted
Every item in `agent-orch/backend_gaps_phase_A_to_C.md` (agent 4's verified list of backend gaps
in Phases A–C), at the owner's request, plus switching agent 4's frontend workarounds to the
new endpoints. Product decisions were not made silently — see "Owner decisions".

## What was already done
Phases A–C by agents 1–3, frontend leftovers by agent 4 (`agent_1.md` … `agent_4.md`).
Inherited tree: `tests/api tests/unit` → 1689 passed, 2 skipped. I re-checked agent 4's gap
claims against the code first; all were accurate.

## Research notes
- §5: org routes authorized from one flat (method, template) → role table, default-deny,
  with a route-walking test — same pattern as the existing project guard.
- §2.2/§8: "Change role (except Owner)" → only owners create, demote or remove owners.
- §2.3: a solo account that wants teammates "offers a plan upgrade" → sharing a project
  requires org membership (a seat); §3.2 makes that a service rule.
- §7.1: org audit view and admin project view are metadata-only.

## Implementation summary

### Authorization and data model
- `app/core/platform_authz.py` — `ORG_ROUTE_ROLES`, `required_org_role()`, `org_role_allows()`.
- `app/api/security.py` — `org_context` dependency (+ `OrgContext`, `org_forbidden`): resolves
  `{slug}`, 404 for non-members, role check with an audited 403 naming the owners, API-token
  scope check (read for GET, write otherwise; project-pinned tokens refused). The project
  `guard` now also requires membership of the project's org and stamps `organization_id` on
  `project.change` audit rows.
- `app/services/member_service.py` — sharing a project needs org membership (409
  `not_an_org_member`).
- `app/services/organization_service.py` — owner-only rules (`set_member_role`,
  `remove_member` take `actor_role`); removal also drops the user's memberships of the org's
  projects (refused if they're a project's only owner) and resets their landing org;
  `delete_organization` refuses while projects or a live Stripe subscription exist, then
  removes members and revokes invites; `accept_invitation_by_id` (shared `_accept` path with
  the token accept, incl. the seat re-check); `resend_invitation`; `rename`; `join_project`;
  `transfer_project`; `list_projects(only_for_user=)`; `owner_emails`; `ensure_unclaimed_org`;
  `expire_trial_if_due` (also applied inside the locked quota checks).
- `alembic/versions/c7e1f3a9d2b4_projects_org_not_null.py` — backfill (owner's org, else the
  holding org `unclaimed-projects`), `SET NOT NULL`, index `(action, target_id)` on the audit
  log. Reversible. `app/models/project.py` now `nullable=False`.
- `app/services/platform_auth_service.py` — bootstrap admin adopts projects out of the
  holding org (the old `organization_id IS NULL` update can't match any more).

### Customer org API (`app/api/orgs.py`, rewritten)
Every `/orgs/{slug}` route goes through `org_context`. New: `PATCH /orgs/{slug}`,
`POST /orgs/invitations/{id}/accept`, `POST /orgs/{slug}/invitations/{id}/resend`,
`POST /orgs/{slug}/projects/{id}/join`, `POST /orgs/{slug}/projects/{id}/transfer`,
`GET /orgs/{slug}/audit`. Invitations return `invite_url` + `emailed`. Members list has
`status` + `last_login_at`. `PUT /account/me/default-organization`; `/account/me` returns
`default_organization_id`. `ProjectCreate`/`ProjectRead` carry `organization_id`.
- `app/services/mail_service.py` (new) — stdlib `smtplib` in a thread, best effort,
  `BUILDER_SMTP_*` settings. **No new dependency.**

### Operator console API (`app/api/admin.py`, `app/services/admin_service.py`)
`AdminOrgRead` gains Stripe ids, period/trial ends, `mrr_cents`, `last_activity_at`. New:
`GET /admin/organizations/{id}/members`, `…/projects` (metadata only),
`GET /admin/subscriptions?status=&q=`, `GET /admin/insights`, `POST /admin/billing/reconcile`.
`PATCH /admin/organizations/{id}/plan` now takes `{plan_id, reason}` and refuses
Stripe-managed orgs (409 `stripe_managed`). `PUT /admin/plans/{id}` validates the id and
audits `changes` (one flat "field: old -> new" string, because audit details are flat and
`max_api_tokens` as a key would trip the secret filter) plus `affected_orgs`.

### Billing
- `app/services/billing_reconcile.py` (new) — ends due platform trials, re-reads every
  Stripe-linked subscription via `stripe_client.fetch_subscription` (new) and applies it with
  the webhook's own `_apply_subscription`; audits only real changes (`billing.reconciled`).
  Run: `python -m app.services.billing_reconcile` (cron, hourly) or the admin button.
- `app/services/stripe_webhook_service.py` — events whose `livemode` doesn't match the
  configured key are ignored and audited `livemode_mismatch`.

### Frontend
- `InvitationsPage` — Accept button per pending invite.
- `OrgConsole` — People: status + last sign-in; Invites: owner role for owners, emailed/link
  state from the API, Resend; Projects: New project in this org, "Add me" (admins), "Move to…"
  (owners); Rename in the header; new Audit log tab (`#/org/<slug>/audit`).
- `ProjectWorkspace` — `useProjectOrg` is one call using `project.organization_id`.
- Admin: org detail shows members, projects, MRR, Stripe links, plan change with a reason
  (disabled for Stripe-managed orgs); Organizations list has MRR + last activity; new
  **Billing** (filters, Stripe links, "Sync with Stripe") and **Insights** tabs.

### Test infrastructure
- `tests/api/conftest.py::add_to_project_org(project_id, email)` — the 17 places in older tests
  that share a project with another user now put that user in the project's org first, as the
  plan requires.
- `tests/api/test_admin.py` bootstrap test uses the holding org; `test_migrations.py` asserts
  the NOT NULL column and the holding org.

## Tests I wrote (TDD evidence)
- `tests/api/test_org_invariants.py` (13): owner-only role/invite/removal rules, 403 names
  owners, project sharing needs org membership, leaving the org drops project access, no
  project in someone else's org, delete refused with projects / live billing, delete removes
  members, project audit stamped with org, every `/orgs/{slug}` route listed, unknown denied.
- `tests/api/test_org_console_api.py` (18): accept by id (and only for the invited address),
  resend rotates and revives, e-mail sent / not configured, rename, People fields, default
  org, members' filtered project list, admin join, transfer (happy path, outsider members,
  not owner of destination, destination cap), org audit scoped + no details, members can't
  read audit, read-only API token can't invite.
- `tests/api/test_admin_orgs_billing.py` (10): org members/projects (metadata only), Stripe
  fields/MRR/last activity, MRR zero without Stripe, plan change needs a reason, refused for
  Stripe-managed orgs, plan id validation, plan diff audit, Billing tab, Insights, support
  staff read-only.
- `tests/api/test_billing_lifecycle.py` (9): expired platform trial → free (on write and on
  plan view), running trial untouched, Stripe trial untouched, reconcile applies a missed
  change once and is quiet after, keeps going when one org fails, operator endpoint, no-Stripe
  run only expires trials, livemode mismatch ignored.

## Test run result
```
tests/api tests/unit  →  1739 passed, 2 skipped, 59 warnings in 203.05s
(baseline 1689 + 50 new; skips and the Starlette 422 deprecation warnings are pre-existing,
the one extra warning is that same deprecation from a new 422 test)
```
Frontend: `npx tsc -b` clean; `npm run lint` 57 warnings (same count as before, none new in
my code); `npx vite build` OK. E2E not run (needs Docker Compose). **Not clicked through in a
browser.**

## Owner decisions (left open on purpose)
1. **Grandfathering plan edits** (§7): edits still apply to every org on the plan at once;
   the audit row now records the diff and how many orgs were affected. Options: snapshot caps
   per subscription, or versioned plans.
2. **Team orgs start on the paid `team` plan for free** — unchanged.
3. **Per-seat price**: MRR assumes `plans.monthly_price_usd` is per seat (Checkout bills
   quantity = seats). Confirm Stripe Price is the source of truth.
4. **Free-plan numbers** (1 project, 3 tokens, 0 MCP) — unchanged.
5. **Org delete** uses the conservative default (refuse while projects / live billing exist).
   Auto-moving projects to the owner's personal org is an alternative.

## Improvement scope — out of current phase
- Built-in TOTP (§4.4 Phase 1) and per-org session TTL policy (§8 "Security policies") are in
  no row — added to queue row 6 in the trigger file. WebAuthn/passkeys still have no row.
- Reconciliation needs a scheduler in deployment (cron/systemd timer); the app has none.
- `org_context` re-reads the org by slug per request; Phase F's RLS binding can reuse
  `request.state.organization_id`, which both guards now set.

## Open items / known issues
- The holding org `unclaimed-projects` has no members by design; it shows in the admin
  Organizations list until the bootstrap admin adopts its projects.

## Round 2 — owner decisions (queue row 4c)
Owner answers: (2) orgs are onboarded by an operator or by paying, nothing else; (3) plan
price is per seat (confirmed — MRR stays as built); (5) deletion is a request with a grace
period. Grandfathering (1) and free-plan numbers (4) were explained and are still open.

- **Team orgs start on `free`** (`DEFAULT_TEAM_PLAN_ID = "free"`). They move up by Checkout →
  webhook, or an operator's plan change. `conftest` keeps `team` for feature tests; a test
  pins the shipped value.
- **Deletion requests**: `DELETE /orgs/{slug}` (owner) → 202, org **locked** (423
  `org_deletion_pending` on every org and project route except `GET /orgs/{slug}` and
  `POST /orgs/{slug}/deletion/cancel`), scheduled `BUILDER_ORG_DELETION_GRACE_DAYS` (7) later.
  Owner revokes with `POST /orgs/{slug}/deletion/cancel`. Refused for personal orgs and while a
  Stripe subscription is live. `OrganizationRead` carries `deletion_requested_at` /
  `deletion_scheduled_for`. Invites to a locked org can't be accepted.
- Operators: `PATCH /admin/organizations/{id}/deletion {grace_days, reason}` (any period from
  now), `POST /admin/organizations/{id}/deletion/execute {reason}` (accept early);
  `AdminOrgRead` shows the deletion fields.
- `app/services/org_deletion_service.py` — `run_due()`; cron
  `python -m app.services.org_deletion_service`. At the deadline the org's **projects are deleted
  with it** (DB cascades), members/invites removed, org soft-deleted, `org.deleted` audited.
- Migration `d8f2a4b6c1e3` (3 columns + partial index). Alembic head: `d8f2a4b6c1e3`.
- Tests: `tests/api/test_org_deletion.py` (14). Suite: **1751 passed, 2 skipped**.

## HANDOFF: continue at row 5 (Phase D.1) — read PLATFORM_SAAS_PLAN.md §4.2, §12.D, then agent_3.md HANDOFF and this file
