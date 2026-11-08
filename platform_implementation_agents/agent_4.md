# Agent 4 report — claude-opus-5-5 — 2026-10-26

## Scope accepted
Work-queue row 4: **frontend leftovers for Phases A–C**, no new backend features (§7, §8, §8.1):
1. Org console `#/org/<slug>` with People, Invites, Projects, Plan tabs, with read-only views and
   an "ask your admin" message for non-admins.
2. "Create organization" entry point and an org switcher in the sidebar.
3. Accept-invitation flow.
4. Org breadcrumb on the project workspace.
5. Admin console: Plans tab and an org detail view with plan change.
6. Missing Phase C billing UI.

Backend gaps found on the way are **not** built. They're listed in
`agent-orch/backend_gaps_phase_A_to_C.md`, a checklist for the earlier agents (requested by the owner).

## What was already done
- Backend for everything above: `app/api/orgs.py` (docstring lists routes), `app/api/admin.py`
  (`/admin/organizations*`, `/admin/plans*`), `app/api/billing.py`.
- `frontend/src/pages/OrgPlanPage.tsx` (agent 2, plus agent 3's "Manage billing" and `past_due`
  banner), `components/QuotaPrompt.tsx` (global 402 modal), admin **Organizations** tab with the
  Limits (override) dialog.
- **Item 6 turned out to be already done.** Agent 3 built "Manage billing" (Billing Portal) and the
  `past_due` banner on the Plan page. The only addition is a `past_due` banner across the other
  org console tabs.

## Research notes
- §8 role matrix: members get read-only plus who to ask; admins get People/Invites/Projects;
  owners also get transfer and delete. §8 says admins change roles "except Owner", so the UI only
  lets owners touch owner rows. **The backend doesn't enforce this** (gaps file, P1).
- §8.1: `#/org/<slug>` → People. `/plan` stays where it was, because Stripe's success/cancel URLs
  point to `#/org/<slug>/plan?checkout=…`.
- Invitation tokens are hashed server-side and returned once, and no email is sent. So the Invites
  tab shows the link once, with copy, and says plainly that the admin has to send it. The link
  format is `<app>/#/invite/<token>`. The token sits in the URL hash, so it isn't sent to the server or written to access logs.
  After accepting, `location.replace` drops it from history.
- `GET /orgs/invitations/pending` returns no token, and accept needs one, so pending invites can be
  listed but not accepted from the list (gaps file, P1). The page explains this and takes a pasted link.

## Implementation summary

### New files
- `frontend/src/pages/OrgConsole.tsx` — the console shell: header with member count, your
  role, plan and status; **Leave** (team orgs); **Delete organization** (owners, team orgs);
  `past_due` banner; tab bar.
  - **People**: name/email/role/joined. Role select for admins (member↔admin; owner rows only
    for owners). **Make owner** (transfer, owners only). **Remove** (admins; owners only for other owners).
  - **Invites**: invite by email + role (member/admin), one-time link box with Copy, pending list
    with time left and **Revoke**, "show past invitations" toggle. A 402 opens the existing
    QuotaPrompt and also shows inline.
  - **Projects**: the org's projects. The ones you're a member of link to `#/p/<id>/overview`,
    the others show a "No access" badge (cross-checked with `GET /projects`). Team orgs get a note that
    creating a project directly in them isn't possible yet.
  - **Plan**: `OrgPlanPage` with a new `embedded` prop (h2 instead of h1).
  - `AskAdmin` shows owners as `mailto:` links. It stands in for §8's "403 with the owner's email",
    which the backend doesn't send.
- `frontend/src/pages/InvitationsPage.tsx` — `#/invitations` and `#/invite/<token>`. With a
  token: an **Accept invitation** button. Joining always takes a click, never just opening a link. Without one: a field for pasting the link. Both list your pending invitations.
  A 404 explains "not valid for <your email>". After joining it goes to the org console. Signed-out
  visitors see the login page first, and the hash survives sign-in (`AuthProvider` doesn't reset it).
- `frontend/src/components/NewOrgDialog.tsx` — name plus optional slug, checked with the
  backend's regex.
- `frontend/src/api/orgEvents.ts` — `notifyOrgsChanged` / `onOrgsChanged` (window event). The
  sidebar refreshes after create, join, leave or delete.

### Edits
- `api/types.ts` — `OrgMember`, `OrgInvitation`, `OrgInvitationCreated`, `PlanWrite`.
- `api/client.ts` — `getOrg`, `createOrg`, `deleteOrg`, `orgMembers`, `setOrgMemberRole`,
  `removeOrgMember` (also used to leave), `transferOrgOwnership` (`to_user_id` is a **query** param
  on the backend), `orgInvitations`, `createOrgInvitation`, `revokeOrgInvitation`,
  `myPendingInvitations`, `acceptInvitation`, `orgProjects`, `adminOrganization`,
  `adminSetOrgPlan` (`plan_id` query param), `adminPlans`, `adminSavePlan`. `adminAudit` gained an
  `organization_id` filter.
- `App.tsx` — routes `#/org/<slug>[/invites|/projects|/plan]`, `#/invitations`, `#/invite/<token>`.
  Removed `page: 'org-plan'`.
- `components/Sidebar.tsx` — `ProjectsSidebar` now has an **Organizations** section
  (switcher: Personal + team orgs, active one highlighted, links to the console), **New
  organization**, and an **Invitations** entry with a count when you have pending ones. It
  replaces the old "Plan & usage" list. `ProjectSidebar` takes an `org` prop and shows
  "Org ›" above the project name, linking to the org's Projects tab.
- `pages/ProjectWorkspace.tsx` — `useProjectOrg(projectId)` finds the owning org by asking each
  of your orgs for its projects, because `ProjectRead` has no `organization_id` (gaps file, P2). One
  `/orgs` call plus one call per org. Swap it for the field when it exists.
- `pages/OrgPlanPage.tsx` — `embedded` prop only.
- `pages/admin/AdminApp.tsx` — **Plans** section. `#/admin/organizations/<uuid>` opens the detail view.
- `pages/admin/AdminPages.tsx`:
  - `AdminOrgDetail`: plan/status, members and projects counts with overrides, **Change plan**
    (select + confirm that warns it doesn't touch Stripe), **Seat / project limits** (reuses
    `OverrideDialog`), paged org-scoped **Audit trail**, and a note that members, projects and Stripe links
    aren't available (no endpoints). Write controls are hidden for read-only support staff.
  - `AdminPlans`: catalog table (price, caps, MCP, SSO/SCIM, hidden) with a **New plan** / **Edit**
    dialog (`PlanDialog`). Empty cap = unlimited. Price entered in dollars, sent as cents. Id
    checked with `^[a-z][a-z0-9_-]*$`. The dialog warns that edits apply immediately (no
    grandfathering on the backend).
  - Org names in the Organizations list link to the detail view.
  - Audit filter gained `org.`, `plan.`, `billing.`, `quota.` event groups (§7 "new event prefixes").
- `index.css` — `.sidebar-org` (breadcrumb link).

No new npm dependencies. No backend files changed.

## Tests I wrote (TDD evidence)
None. The frontend has no test runner (`package.json` has no test script or test deps), and
adding one would be a new dependency. Verification was the type checker, lint, build and the
backend suite below. I didn't click through the UI in a browser. That's the first thing to do
before merge (see Open items).

## Test run result
```
tests/api tests/unit  →  1689 passed, 2 skipped, 58 warnings in 234.07s
(unchanged from the inherited tree — no backend files touched; skips and Starlette 422 deprecation warnings are pre-existing)
```
Frontend: `npx tsc -b` clean. `npm run lint` shows 57 warnings, the same as before I started (no new ones in my files;
the listed ones are pre-existing at shifted line numbers). `npx vite build` OK, with only the
pre-existing chunk-size notice. E2E (`tests/e2e`) not run: it needs the Docker Compose stack.

## Improvement scope — out of current phase
All backend items are in **`agent-orch/backend_gaps_phase_A_to_C.md`** (P1/P2/P3, with file
pointers and the frontend workaround to remove for each). The main ones:
- Admins can make or unmake owners server-side. Project membership ignores org membership.
  `projects.organization_id` is still nullable. The guard has no `required_org_role`.
- Pending invites can't be accepted without the link. No invite email or resend.
- Deleting an org doesn't cancel Stripe or detach projects.
- `ProjectRead`/`ProjectCreate` have no `organization_id`. Members see all org projects.
- Admin org detail can't show members, projects or Stripe ids. No Billing tab endpoint. Plan edits
  aren't grandfathered and their audit has no diff.
- Built-in platform TOTP (§4.4 Phase 1) doesn't exist, and row 6's "require MFA" policy depends on it.

Frontend follow-ups (not blocking):
- The admin plan-change and limits dialogs could share one "reason" field once the backend asks
  for a reason on plan changes.
- `useProjectOrg` makes N+1 calls. Delete it once `ProjectRead.organization_id` lands.

## Open items / known issues
- **Not checked in a browser.** Before merge, click through: create an org → invite (copy
  link) → open the link as the invitee → accept → role change, transfer, remove, leave, delete;
  admin Plans edit and org detail plan change.
- The sidebar marks the active org by comparing `window.location.hash` at render time. That's fine
  because the whole tree re-renders on `hashchange`.
- Personal orgs show all four tabs (§2.3: "the UI exposes the admin surface"). Inviting into a
  personal org works server-side but is capped by the free plan's seats, so the 402 prompt points
  to upgrading.

HANDOFF: continue at Phase D.1 (queue row 5) — read PLATFORM_SAAS_PLAN.md §4.2, §12.D
