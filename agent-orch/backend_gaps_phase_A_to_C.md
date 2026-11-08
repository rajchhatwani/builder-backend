# Backend gaps — Phases A–C (found by agent 4 while building the frontend)

> **Status 2026-10-26: worked through by agent 2 (queue row 4b).** Every item is ticked except
> the owner decisions, which are marked **OWNER DECISION**. Details: `platform_implementation_agents/agent_2b.md`.

> Written 2026-10-26 by agent 4 (frontend row). These are things `PLATFORM_SAAS_PLAN.md` asks
> for that the **backend does not provide yet**. Agent 4 had a "no new backend features" rule,
> so none of them were built. Everything below was checked against the code, not taken from
> earlier reports.
>
> **For the agent picking this up:** follow the TDD cycle in `trigger_and_report_here.md`. When an
> item lands, tick it here and, where noted, switch the frontend workaround over (the files are
> listed). Run `uv run pytest tests/api tests/unit -q` (currently **1689 passed, 2 skipped**).
>
> Items for Phases D–F that are already rows 5–8 of the work queue are listed at the bottom
> only so nothing gets lost. They are **not** gaps in A–C.

Priority: **P1** = plan invariant or security/billing correctness. **P2** = a promised console
feature. **P3** = polish or a product decision.

---

## 1. Authorization and data model (§2.2, §3.2, §5, §12.A.3)

- [x] **P1 — Guard has no `required_org_role`.** §5 and §12.A.3 call for the request guard to
  resolve the owning org and check an org role per route template. `app/core/platform_authz.py`
  and `app/api/security.py` have no org concept. `/orgs/*` routes check roles inline with
  `_require_role` in `app/api/orgs.py`, which works but isn't the flat (method, template) → role
  table the plan describes, and project routes never look at the org at all.
  → DONE: `platform_authz.ORG_ROUTE_ROLES` + `required_org_role()` (default-deny, test walks every `/orgs/{slug}` route); `security.org_context` resolves the org, checks the role, enforces API-token scopes, and audits denials. The project guard now also requires membership of the project's org.
- [x] **P1 — `projects.organization_id` is still nullable.** §3.2 says `NOT NULL`. The Phase A
  migration (`b2c3d4e5f6a7`) adds it as `nullable=True`. Needs a follow-up migration once every
  row is backfilled (the backfill already attaches projects), plus a model change.
  → DONE: migration `c7e1f3a9d2b4` backfills (owner's org, else holding org `unclaimed-projects`) then sets NOT NULL; model updated; bootstrap admin adopts from the holding org.
- [x] **P1 — Project membership ignores org membership.** §3.2: "the service enforces *user must
  be a member of `projects.organization_id` before they can be added to this project*."
  `app/services/member_service.py` has no org check. Anyone with an account can be added to any
  project, whatever their org.
  → DONE: `MemberService.add` → 409 `not_an_org_member`; leaving/removal from an org deletes that user's memberships of its projects (refused with 409 `sole_project_owner` if they're a project's only owner).
- [x] **P1 — Admins can grant or strip Owner.** §2.2 and §8 ("Change role (except Owner)").
  `PATCH /orgs/{slug}/members/{user_id}` only requires `admin`, so an admin can promote any
  other member to owner, or demote an owner while another owner remains. `POST /orgs/{slug}/invitations` also accepts `role: "owner"` from an admin.
  Owner changes should need the `owner` role. *(Frontend already hides these choices from
  admins: `frontend/src/pages/OrgConsole.tsx` `roleChoices`, and the invite form offers member/admin only.)*
  → DONE: role change, removal and invite with/of an owner need the owner role (403 with owner emails).
- [x] **P2 — Project-route audit rows have no `organization_id`.** §3.2: "every org-scoped action
  stamps it". The guard in `app/api/security.py` records `project.change` without it, so an
  org-scoped audit view (§8) and the admin org audit tail (§7) miss all project activity.
  Stamp it from `projects.organization_id`.
  → DONE: stamped in `security.guard`.
- [x] **P2 — `default_organization_id` isn't exposed.** §3.2 says it's "where the UI drops
  someone when they sign in and belong to several orgs". It isn't on `UserAccount`
  (`/account/me`), and nothing sets it except sign-up. Expose it and add a way to change it.
  → DONE: on `GET /account/me`; `PUT /account/me/default-organization`.

## 2. Customer org API (§8, §12.A.4)

- [x] **P1 — Accept a pending invite without the link.** `GET /orgs/invitations/pending` lists
  the signed-in user's invites, but `POST /orgs/invitations/accept` needs the raw token, which is
  only shown once to the inviting admin. So the list can't be acted on. Add
  `POST /orgs/invitations/{id}/accept` that checks the invite's email equals the signed-in
  user's (same checks as token accept, incl. the seat re-check and `BillingService.sync_seats`).
  *(Frontend workaround: `frontend/src/pages/InvitationsPage.tsx` lists invites and asks for
  the link. Add an Accept button per row once this exists.)*
  → DONE: `POST /orgs/invitations/{id}/accept`; Accept button on `InvitationsPage`.
- [x] **P1 — Invitations are never emailed.** The admin has to copy the link by hand (the UI
  says so). §8 "Invites … resend" assumes delivery. Needs a mail sender (check for an existing
  SMTP integration before adding a dependency) and the invite link format
  `<public_app_url>/#/invite/<token>` (the frontend route that already exists).
  → DONE: `app/services/mail_service.py` (stdlib SMTP, no new dependency), `BUILDER_SMTP_*`; response carries `invite_url` and `emailed`. Unconfigured → UI shows the link as before.
- [x] **P2 — Resend an invitation.** §8 lists "resend". No endpoint. Since the token is
  hashed, resend = rotate the token (new hash, new expiry) and send it again. Return the new
  token once, like create.
  → DONE: `POST /orgs/{slug}/invitations/{id}/resend` rotates token + expiry (re-checks the seat for an expired invite).
- [x] **P2 — `ProjectRead` has no `organization_id`.** The workspace breadcrumb (§8.1) has to
  call `/orgs/{slug}/projects` for every org the user is in to find the owner org.
  *(Workaround: `useProjectOrg` in `frontend/src/pages/ProjectWorkspace.tsx`. Replace it with
  the field.)* Add `organization_id` (and ideally `organization_slug` / name) to `ProjectRead`.
  → DONE: `organization_id` on `ProjectRead` (slug/name come from `/orgs`); `useProjectOrg` is now one call.
- [x] **P2 — Can't create a project inside a team org.** `ProjectCreate` has no
  `organization_id`. New projects always land in the creator's default org (agent 1 flagged
  this). Add the optional field, check membership plus the project cap for *that* org.
  *(The org console Projects tab says this isn't available yet. Add a "New project" button there.)*
  → DONE: `ProjectCreate.organization_id`; "New project" on the org Projects tab.
- [x] **P2 — Members see every org project.** §8: members see "the org's projects list
  (filtered to projects they're a member of)". `GET /orgs/{slug}/projects` returns all of them
  to any member. Filter for `member`, keep the full list for admin/owner.
  *(Frontend currently marks the ones you can't open as "No access".)*
  → DONE: members get only their projects; admins/owners all.
- [x] **P2 — Admins can't add themselves to an org project.** §8 Projects: "Can add themselves
  to any one". No endpoint (the project members API needs a project owner).
  → DONE: `POST /orgs/{slug}/projects/{id}/join` (admin+); "Add me" button.
- [x] **P2 — Can't move a project between orgs.** §8 Projects: "can transfer a project between
  orgs they own". No endpoint. Must re-check the destination's project cap and `past_due`.
  → DONE: `POST /orgs/{slug}/projects/{id}/transfer` (owner of both; all project members must be in the destination; destination cap + past_due apply); "Move to…" select.
- [x] **P2 — People table is missing fields.** §8 People: "role, email, status, 2FA on/off,
  last sign-in". `OrganizationMemberRead` has only user_id/email/name/role/joined_at. Add
  account status and `last_login_at` (both exist on `PlatformUser`). "2FA on/off" can't be shown
  yet: **built-in platform TOTP (§4.4 Phase 1) doesn't exist at all**. See the bottom table.
  → DONE: status + last sign-in. 2FA column waits for built-in MFA (queue row 6).
- [x] **P2 — 403 doesn't name an owner.** §8: "Hitting any admin-only panel returns a 403 with
  the owner's email". `_require_role` returns a plain 403. Put owner email(s) in `details`.
  *(Frontend works around it by reading owners from the members list: `AskAdmin` in
  `OrgConsole.tsx`.)*
  → DONE: `details[0] = {needed_role, owner_emails}`.
- [x] **P2 — Rename an org.** `OrganizationUpdate` exists in `app/schemas/organization.py` but no
  `PATCH /orgs/{slug}` route uses it.
  → DONE: `PATCH /orgs/{slug}`; Rename button in the console header.
- [x] **P2 — Org-scoped audit log.** §8 Admins: "Audit log. Org-scoped slice of
  `platform_audit_log` … queries receive an unconditional `organization_id = X` filter", and §8.1
  route `#/org/<slug>/audit`. No `GET /orgs/{slug}/audit`. Must strip customer-data `detail`
  per §7.1. Depends on the P2 project-route stamping above to be useful.
  → DONE: `GET /orgs/{slug}/audit` (admin+, no `detail`/IP); Audit log tab `#/org/<slug>/audit`.
- [x] **P1 — Deleting an org leaves billing and projects alive.** `delete_organization` only
  sets `deleted_at`. Its docstring says "members and projects detach", but nothing does that.
  Projects stay reachable through `project_members`, and a live Stripe subscription keeps
  charging. On delete: refuse (409) or cancel when there's a live Stripe subscription
  (`BillingService.has_live_stripe_subscription`), and decide what happens to the projects
  (refuse while projects exist, or move them to the owner's personal org). This is a product
  decision, so ask the owner.
  → DONE with the conservative default: refused (409 `org_has_projects` / `org_has_billing`) until projects are moved/deleted and Stripe is canceled; members and pending invites are removed; landing orgs reset. **Owner may prefer auto-move to the owner's personal org.**
  → **REPLACED (row 4c, owner decision):** deletion is now a request — locked at once, owner can revoke during a grace period (default 7 days, operator-adjustable), then the org and its projects are deleted by `org_deletion_service`.

## 3. Operator console API (§7, §12.A.5)

- [x] **P2 — Org detail data.** §7: "Click into an org → see members (read-only), projects
  (metadata only), SSO/SCIM status, Stripe link, audit tail". Only the audit tail is possible
  today (`/admin/audit?organization_id=`). Missing: `GET /admin/organizations/{id}/members`,
  `GET /admin/organizations/{id}/projects` (metadata only, §7.1), and
  `stripe_customer_id` / `stripe_subscription_id` / `current_period_end` / `trial_ends_at` on
  `AdminOrgRead` for the Stripe deep link. *(The frontend detail view at
  `#/admin/organizations/<id>` says these aren't available yet.)*
  → DONE: `GET /admin/organizations/{id}/members|projects`, Stripe ids/period/trial on `AdminOrgRead`; detail page shows them with Stripe Dashboard links.
- [x] **P2 — MRR and last activity on the Organizations list.** §7: "plan, member count,
  project count, MRR, status, last activity". `AdminOrgRead` has no MRR (plan price × seats or
  flat) and no last-activity time (latest audit row for the org).
  → DONE: `mrr_cents` (Stripe-paying orgs: plan monthly price × members) and `last_activity_at`.
- [ ] **P1 — Plan edits aren't grandfathered and their audit has no diff.** §7 Plans tab:
  "existing subscribers are grandfathered until they change plans, and the change is audited."
  `AdminService.upsert_plan` mutates the row in place, so new caps hit every org at once. The
  audit `detail` is only `{plan_id}`, with no before/after. At minimum record old→new values.
  Grandfathering needs a design (e.g. snapshot caps onto `subscriptions`, or versioned plans).
  Ask the owner. *(The admin Plans dialog warns that changes apply immediately.)*
  → PARTLY: audit now records `changes` (old -> new) and `affected_orgs`; plan ids validated. **Grandfathering is still open — owner decision** (snapshot caps per subscription vs. versioned plans).
- [x] **P2 — `PUT /admin/plans/{id}` doesn't validate the id.** Any path string becomes a plan
  id (the column is `varchar(40)`). Add a pattern/length check. The UI enforces
  `^[a-z][a-z0-9_-]*$`.
  → DONE: `^[a-z][a-z0-9_-]{0,39}$`, else 422.
- [x] **P2 — Manual plan change vs Stripe.** `PATCH /admin/organizations/{id}/plan` changes
  `plan_id` without touching Stripe. For an org with a live Stripe subscription, the next
  `customer.subscription.updated` resets it. Either refuse for Stripe-managed orgs, or add a
  "pinned by operator" flag the webhook respects. Also: `plan_id` is a query param, and the
  change takes no `reason` (overrides require one, §6.5). Ask for one for consistency.
  → DONE: refused 409 `stripe_managed` for orgs with a live Stripe subscription; body `{plan_id, reason}` (reason audited).
- [x] **P2 — Billing tab.** §7: "List subscriptions, overdue invoices, trial expirations.
  Deep-link to the Stripe Dashboard." No endpoint. Minimum: `GET /admin/subscriptions?status=`
  with plan, status, period end, trial end, Stripe ids. Not built in the UI (nothing to call).
  → DONE: `GET /admin/subscriptions?status=&q=`; admin Billing tab with Stripe links and a "Sync with Stripe" button.
- [x] **P3 — Insights.** §7: signups/day, orgs/day, active orgs (7 days), total projects, MCP
  calls in 24 h, denied-by-quota count, all from `platform_audit_log`. No endpoint, no UI. Not
  in any phase step of §12, so the owner should decide which phase gets it.
  → DONE: `GET /admin/insights` + admin Insights tab (from audit log + account rows only).

## 4. Billing (§6.3, §6.4, §10, §12.B–C)

- [x] **P1 — Trials never expire.** `trial_ends_at` is only written by the Stripe webhook.
  Nothing moves a `trial` subscription on when it passes, for orgs without Stripe. Decide
  whether non-Stripe trials exist at all. If they do, add an expiry check (on read, or a job).
  → DONE: a platform trial (no Stripe subscription) past `trial_ends_at` drops to `free`/`canceled` (audited `billing.trial_expired`) — lazily on the next write or plan view, and by the reconcile job. Stripe trials stay Stripe's.
- [x] **P1 — No reconciliation job.** Agent 3's note: a webhook Stripe gives up on leaves the row
  stale forever. Periodic "fetch subscription → re-apply" (the generator's payments feature
  has a `reconcile.py` pattern).
  → DONE: `app/services/billing_reconcile.py` (`python -m app.services.billing_reconcile`, hourly cron) + `POST /admin/billing/reconcile`; reuses the webhook's apply rules; audits only real changes.
- [x] **P3 — Team orgs start on the paid `team` plan for free.** Agents 2 and 3 flagged it.
  A new team org can't buy Team (Checkout refuses the current plan). Product call: start on
  `free`/`trial`, or allow checkout of the current plan when there's no Stripe subscription.
  → **OWNER DECISION — unchanged.**
  → **DECIDED + DONE (row 4c):** new team orgs start on `free`; they move up only by paying or by operator onboarding.
- [x] **P3 — Per-seat price.** §10 describes a "seat line item billed at the plan's per-seat
  price". `plans` has only `monthly_price_usd`, and per-seat pricing lives only in the Stripe Price.
  Confirm with the owner that the Stripe Price is the source of truth. If so, document it in
  `.env.example`.
  → **OWNER DECISION — unchanged.** MRR currently assumes `monthly_price_usd` is per seat (matches Checkout quantity = seats).
  → **DECIDED:** the plan price is per seat (MRR as built).
- [ ] **P3 — Free-plan numbers.** Agent 2: free = 1 project, 3 API tokens, 0 MCP tokens blocks
  existing multi-project users and all MCP on free. The owner should confirm before deploy
  (`PUT /admin/plans/free`, now editable in the admin Plans tab).
  → **OWNER DECISION — unchanged.**
- [x] **P3 — Small hardening from agent 3.** Index `(action, target_id)` on
  `platform_audit_log` for webhook dedupe at volume. Check `livemode` on webhook events.
  Optionally credit seats on removal instead of high-water mark.
  → DONE: `(action, target_id)` index (migration `c7e1f3a9d2b4`), `livemode` mismatch ignored + audited. Seat credit on removal left as high-water mark (§6.4).
- [x] **P3 — Ruff findings in `app/api/orgs.py`.** Unused imports (`request_info`, `AppError`),
  unused `AccountStatus` in the org service, B008 on `Path`. Flagged by agents 2 and 3, still
  untouched.
  → DONE: `orgs.py` rewritten; touched files ruff-clean.

---

## Round 2 (found by agent 4 while building row 4d, 2026-10-26)

- [x] **P2 — 423 `org_deletion_pending` doesn't say which org.** `org_deletion_pending()` in
  `app/api/security.py` puts only `deletion_scheduled_for` in `details`. A 423 from a project
  route leaves the UI guessing which org is locked. Add `organization_slug` (and name) to
  `details[0]`. *(Workaround: `frontend/src/components/OrgLockedPrompt.tsx` calls `GET /orgs` and
  links to the locked ones. Switch it to the slug from the 423.)*
- [x] **P2 — `GET /projects` lists projects of locked orgs.** Opening any of them answers 423.
  Either leave them out of the list, or add `organization_locked: bool` (or the org's
  `deletion_scheduled_for`) to `ProjectRead`. *(Workaround: `frontend/src/pages/ProjectsPage.tsx`
  calls `GET /orgs`, finds locked orgs and renders their projects as locked cards without
  further calls. Switch it to the field.)*
  → DONE (agent 5, row 5): the 423 details carry `organization_id/slug/name`; `ProjectRead` has
  `organization_locked` + `organization_deletion_scheduled_for` (still listed, flagged). The UI uses both.

---

## Already queued for later rows — listed so nothing is lost (NOT A–C gaps)

| Plan item | Queue row |
|---|---|
| `sso_connections` / `sso_domains`, DNS verify, SAML/OIDC, JIT, `allow_sso` 402 gate (§4.2, §6.2) | 5 |
| SSO & SCIM tab `#/org/<slug>/sso`, operator SSO status/test (§8, §8.1) | 6 |
| Security policies `#/org/<slug>/policies`: require MFA, session TTL (§4.4, §8) | 6 (MFA policy). **Session TTL policy is in no row. Add it to row 6.** |
| Built-in TOTP for platform users, mandatory MFA for platform admins (§4.4 Phase 1) | **No row, and row 6's "require MFA" policy depends on it. Add it before or inside row 6.** |
| SCIM 2.0, `allow_scim` gate, SCIM seat check + `sync_seats` (§4.3, §6.2) | 7 |
| RLS (§3.3), impersonation + per-org "allow impersonation" toggle (§4.5, §7.1, §8 policies), per-org export, GDPR delete, docs (§9, §11) | 8 |
| WebAuthn / passkeys (§4.4 "Phase 2") | **No row. Ask the owner.** |
| Metered line items (§10, "starts off") | **No row (deliberately off).** |
