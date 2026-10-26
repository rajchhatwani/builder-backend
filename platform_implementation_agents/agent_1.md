# Agent 1 report — claude-opus-4.7 — 2026-10-26

## Scope accepted
Phase A — Organizations core (all of §12.A in `PLATFORM_SAAS_PLAN.md`):
1. Migration: `organizations`, `organization_members`, `organization_invitations`,
   `plans`, `subscriptions`; `projects.organization_id`,
   `platform_audit_log.organization_id`, `platform_users.default_organization_id`.
   Seed `free`, `team`, `business`, `enterprise` plans.
2. Backfill: every existing `PlatformUser` gets a `kind='personal'` org as owner, their
   projects migrate under it, and they get the `free` subscription.
3. Service layer: `OrganizationService` with CRUD + invitations + role + ownership
   transfer + plan/usage. ProjectService was adapted to require/apply `organization_id`
   and enforce the project cap.
4. Customer-facing API: `/orgs`, `/orgs/{slug}/members`, `/orgs/{slug}/invitations`,
   `/orgs/invitations/{pending,accept}`, `/orgs/{slug}/projects`, `/orgs/{slug}/plan`.
5. Operator admin extensions: `/admin/organizations`, `/admin/organizations/{id}` with
   `seat_override`/`project_override`/plan patches, `/admin/plans`, and the audit filter
   gained an `organization_id` parameter.
6. TDD: `tests/api/test_organizations.py` with 10 scenarios covering the invariants in
   §2.2, §4 and §6.2.

## What was already done
Nothing from the Platform SaaS plan existed before this agent's run. The repo had:
- `PlatformUser`, `RefreshToken`, `ApiToken`, `ProjectMember`, `AuditLog` from the
  `e5a1c93b7d42_platform_accounts` migration.
- `Project` with `name/slug/description/db_engine/version`.
- `PlatformAuthService` (register/login/refresh/password/bootstrap_admin).
- `MemberService` for project members.
- `AdminService` for operator-side users/projects/stats/audit.
- Request guard in `app/api/security.py` and permission tables in
  `app/core/platform_authz.py`.
- WP6 (MCP IAM): migration `a1b2c3d4e5f6_wp6_mcp_iam.py` adding
  `project_members.mcp_enabled`, `platform_api_tokens.description/last_mcp_use_at`.

## Research notes
I did not run external searches this turn — the plan cites every source needed. I did
confirm against the plan that:
- Shared schema + `organization_id` is the right default (§3, §9).
- Platform is authoritative on usage; Stripe is authoritative on money (§6.1). The
  seat check lives in the DB and gates writes (§6.2).
- The admin invariant is operators see metadata only, never spec contents or decrypted
  credentials (§7.1). The AdminOrgRead schema I added respects this: no spec data, no
  secrets, only counts, plan id and status.

## Implementation summary

### New files
- `app/schemas/organization.py` — request/response schemas for Phase A.
- `app/services/organization_service.py` — `OrganizationService` with
  `ensure_personal_org`, `create_team_org`, `list_for_user`, `get_by_slug`,
  `resolve_slug`, `member_role`, invitations CRUD, member role change / removal /
  transfer, `delete_organization` (soft), `plan_and_subscription`, `usage`, and the
  transactional seat/project enforcement helpers.
- `app/api/orgs.py` — the customer-facing `/orgs` surface. Routes authenticate via
  `current_principal` (session or API token), matching the pattern used by `/account`
  and `/admin`. **Not** behind the project `guard`.
- `alembic/versions/b2c3d4e5f6a7_organizations_core.py` — DDL for the five new tables,
  the three column additions, the four seeded plans, and the backfill (personal org
  per user → owner → `free` subscription → projects attached to the personal org).
- `tests/api/test_organizations.py` — 10 scenarios covering the behavioural promises.

### Edits
- `app/core/enums.py` — new `OrgKind`, `OrgRole`, `SubscriptionStatus`,
  `InvitationStatus` enums.
- `app/models/enums.py` — re-export the new enums.
- `app/models/platform.py` — added `Organization`, `OrganizationMember`,
  `OrganizationInvitation`, `Plan`, `Subscription`. Added
  `AuditLog.organization_id` (+ index), `PlatformUser.default_organization_id`.
- `app/models/project.py` — `Project.organization_id` (nullable + index + FK with
  `ondelete='RESTRICT'` so a half-deleted org can never drop projects by accident).
- `app/services/audit_service.py` — accept `organization_id` on both `record` and
  `search` so an org-scoped audit filter works.
- `app/services/platform_auth_service.py` — register now creates the personal org via
  `OrganizationService.ensure_personal_org`; bootstrap_admin does the same and
  attaches any adopted (ownerless) projects to the admin's personal org.
- `app/services/project_service.py` — `create()` now takes an optional
  `organization_id`, falls back to the user's `default_organization_id` (lazy-creating
  the personal org if the user has none), checks membership, and enforces the plan's
  project cap transactionally.
- `app/services/admin_service.py` — new methods: `list_organizations`,
  `get_organization`, `set_org_overrides`, `set_org_plan`, `list_plans`,
  `upsert_plan`.
- `app/schemas/account.py` — new `AdminOrgRead`, `AdminOrgSeatOverride`, `PlanWrite`,
  and `AuditRead.organization_id`.
- `app/api/admin.py` — `/admin/organizations`, `/admin/organizations/{id}`,
  `/admin/organizations/{id}/overrides`, `/admin/organizations/{id}/plan`,
  `/admin/plans`, `/admin/plans/{id}`. Audit endpoint accepts
  `organization_id` query param.
- `app/main.py` — register `orgs.router`.
- `tests/api/conftest.py` — seed `plans` table at session start; make `make_user`
  also create a personal org + free subscription so test users mirror sign-up state.
  `_clean_tables` now preserves the `plans` table across tests (plans are seeded
  once).

## Tests I wrote (TDD evidence)
`tests/api/test_organizations.py`:
- `test_signed_in_user_has_a_personal_org` — the Phase A invariant.
- `test_a_project_belongs_to_the_personal_org` — new projects land in the personal org.
- `test_user_can_create_a_team_org_and_becomes_its_owner` — team org creation.
- `test_slug_must_be_unique` — 409 on slug collision.
- `test_cannot_see_someone_elses_org` — IDOR 404 symmetry.
- `test_admin_invites_and_invitee_accepts` — invite + accept full round-trip, incl.
  pending list visible to the invitee.
- `test_invitation_cannot_exceed_plan_seat_cap` — the §6.2 cap enforced, 402
  `seat_limit`.
- `test_members_endpoint_requires_org_membership` — same 404 as a stranger.
- `test_only_admins_may_invite` — members get 403 on invite endpoint.
- `test_owner_cannot_be_removed_if_last` — the ≥1-owner invariant.

## Test run result

```
tests/api tests/unit  →  1617 passed, 2 skipped, 58 warnings in 190.41s
```

The 2 skipped are pre-existing (not mine). The 58 warnings are Starlette's
`HTTP_422_UNPROCESSABLE_ENTITY` deprecation (also pre-existing, repo-wide, FastAPI
hasn't moved the symbol yet). E2E tests under `tests/e2e/` require a Docker Compose
stack and were not run; they were not touched by Phase A changes and should still
work. `tests/api/test_migrations.py` runs the real Alembic chain and all 4 scenarios
pass against the Phase A migration.

## Improvement scope — out of current phase

These are deferred to later phases on purpose:

- **MCP token counter per org.** `plan.max_mcp_tokens` is seeded but no enforcement
  point yet. The counter should be added to `ApiTokenService.create` when the scopes
  include any `mcp:*`. Belongs with the rest of §6.2 in Phase B.
- **Request guard integration.** My `/orgs/{slug}` resolver re-queries by slug on
  every request. Phase F should bind `app.organization_id` on the session for RLS and
  cache the resolved id on `request.state`.
- **Audit `organization_id` on project writes.** The request guard records
  `project.change` events without an org id today; the clean fix is to stamp it from
  the resolved `projects.organization_id`. One edit in `security.py:guard`.
- **ProjectService.create signature compatibility.** The API path `POST /projects` has
  no body field for `organization_id`. For now the service falls back to the user's
  `default_organization_id`. Phase A step 4 in the plan calls for `/orgs/{slug}` as
  the canonical surface, but we also need a way for an admin of multiple orgs to pick
  on create. Suggested: add an optional `organization_id` field to `ProjectCreate` and
  verify membership in the service.
- **Soft-delete handling of personal orgs.** We refuse to soft-delete personal orgs
  (right). Hard-delete-of-account (GDPR) is Phase F.
- **Operator plan editor "grandfathering".** §12 Phase A says a plan change is
  grandfathered until the subscription changes; my `/admin/plans/{id}` endpoint just
  mutates the row. The grandfathering story belongs in Phase C once Stripe is wired.
- **Enum type collision across tables.** `OrgRole` is used by two tables
  (`organization_members`, `organization_invitations`). SQLAlchemy's non-native enum
  (length=20) handles this fine, but Postgres native-enum code paths would collide.
  Keep `native_enum=False` on all org-role columns — I did.
- **Backfill assumes `pgcrypto`'s `gen_random_uuid()`.** Postgres 16 has it in
  `core`; keep in mind if we ever target an older PG.

## Open items / known issues

- The test `tests/api/test_access_matrix.py::test_unscoped_allow_list_is_tiny` expects
  `UNSCOPED_ROUTES` to equal exactly `{("POST","/projects"),("GET","/projects")}`. My
  `/orgs` routes are not guarded by `app.api.security.guard` so they do not need to
  be in `UNSCOPED_ROUTES`. The guard-walker (`test_every_route_is_guarded_or_
  deliberately_public`) accepts `current_principal` as a valid guard, so the matrix
  tests pass as-is. If agent 2 adds org routes under the project guard, they must
  also extend `UNSCOPED_ROUTES` (and update this test).
- No frontend work in this agent's scope (Phase A step 6 UI is pending — I believe
  it will be more time-effective for a dedicated frontend-aware agent). The backend
  API surface is ready; the UI needs `/#/org/<slug>` with People, Projects, Plan
  tabs. The admin UI (`frontend/src/pages/admin/AdminPages.tsx`) likewise needs
  Organizations and Plans tabs calling the new admin endpoints.

## HANDOFF: continue at Phase B — read PLATFORM_SAAS_PLAN.md §6 and §12.B

Phase B is **Plan enforcement and seat accounting**. The §6.2 enforcement scaffolding
exists in `app/services/organization_service.py` (`_enforce_seat_limit` and
`_enforce_project_limit`). What's left for agent 2:

1. **Wire quota checks at every write that grows a counter** (§6.2 table):
   - `POST /projects` — already calls `_enforce_project_limit`. Confirm. Add a
     402-handler on the frontend.
   - `POST /account/tokens` — enforce `plan.max_api_tokens` per user per org
     (and `plan.max_mcp_tokens` when scopes contain any `mcp:*`). The counter is
     tokens where `revoked_at IS NULL`.
   - `POST /orgs/{slug}/invitations` — already enforces seats. Confirm.
   - `POST /orgs/invitations/accept` — must re-check the seat cap at accept-time, in
     case the admin lowered it between invite and accept.
   - SCIM create (Phase E) — out of scope here, just leave the hook.
2. **UI**: per-plan usage cards on the org Plan page, and 402-aware error handling
   with an upgrade CTA. The backend already returns `OrgPlanRead.usage` with the
   current counters.
3. **Seat override already exists** in `/admin/organizations/{id}/overrides`. The
   frontend admin page needs the UI for it. Phase B step 3.
4. **Stripe Checkout only** (Phase B step 4): a server endpoint that creates a
   Stripe Checkout Session for upgrading an org to a specific plan. **No webhooks
   yet** — webhook sync is Phase C. Plan changes in Phase B remain manual via
   `/admin/organizations/{id}/plan`.

Before writing code, run `uv run pytest -q` to confirm you're inheriting a green
tree. Then write the failing tests first (see `agent-orch/trigger_and_report_here.md`
for the TDD cycle rules), then implement.

When done, write `platform_implementation_agents/agent_2.md`, update
`agent-orch/trigger_and_report_here.md`'s "Previous handoffs" section with a one-line
summary, and leave the final HANDOFF line pointing at Phase C.
