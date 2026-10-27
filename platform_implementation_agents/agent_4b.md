# Agent 4 (second pass, queue row 4d) report — claude-opus-5-5 — 2026-10-26

## Scope accepted
Queue row 4d: frontend for rows 4b + 4c, no backend changes.
1. Org deletion request UI: the confirm text, a locked org console with owner-only **Cancel
   deletion**, a global 423 `org_deletion_pending` handler, and a "locked" marker in the sidebar.
2. Admin console: show `deletion_scheduled_for` in the list and on the detail page. The detail page
   gets **Change period** and **Delete now**.
3. Team orgs start on `free`: tell the creator, and link to the Plan tab.
4. Verify row 4b's screens and fix what's broken.

Started after the watcher on `trigger_and_report_here.md` saw row 4c ticked by agent 2.

## What was already done
- Row 4: my org console, invitations, breadcrumb, admin Plans/org detail (`agent_4.md`).
- Row 4b: agent 2 closed every backend gap and switched most screens over: accept by id, resend,
  e-mail state, People status/last sign-in, Projects new/join/move, Audit tab, rename, admin
  members/projects/MRR/Stripe links/Billing/Insights (`agent_2b.md`).
- Row 4c (backend only): `DELETE /orgs/{slug}` → 202 + lock, `POST /orgs/{slug}/deletion/cancel`,
  admin `PATCH …/deletion` and `POST …/deletion/execute`, `deletion_*` fields, and team orgs on `free`.

## Research notes
- **A locked org answers 423 on every org and project route except `GET /orgs/{slug}` and the
  cancel.** The console used to load org, members and plan together, so a locked org would have
  shown "Can't load this organization". It now loads the org first and stops there if it's locked.
- **`GET /projects` still lists projects of locked orgs.** Each project card on the Projects page
  fetches entities, auth and validation, so every visit would have hit 423 and opened the new
  prompt. The page now looks up locked orgs (`GET /orgs`) and draws those projects as locked
  cards without calling anything about them.
- The 423 body has only `deletion_scheduled_for`, not which org. The global prompt calls
  `GET /orgs`, which is never locked, and links to the locked org (or lists them if several).
- Row 4b was checked against the running app's OpenAPI rather than in a browser (see Tests):
  every org/admin call in `api/client.ts` exists with the same method, query params and body
  fields, and every response type in `api/types.ts` has exactly the API's fields.

## Implementation summary

### New files
- `frontend/src/components/OrgLockedPrompt.tsx` — global 423 modal, mounted next to `QuotaPrompt`
  in both places in `App.tsx`. "Scheduled for deletion on <date>, with all its projects; locked
  until then; an owner can cancel it", with **Open <org>**.
- `frontend/src/api/dates.ts` — `formatDeletionDate()`. It has its own file because exporting it
  from a component file adds a lint warning.

### Edits
- `api/client.ts` — `onOrgLocked()` listener, fired for 423 + `org_deletion_pending` (beside the
  402 one). `deleteOrg` now returns the `Organization` (202). New: `cancelOrgDeletion`,
  `adminRescheduleOrgDeletion(id, graceDays, reason)`, `adminExecuteOrgDeletion(id, reason)`.
- `api/types.ts` — `deletion_requested_at` / `deletion_scheduled_for` on `Organization` and
  `AdminOrg`. New `OrgLockedDetail`.
- `pages/OrgConsole.tsx`
  - Loads the org first and skips members/plan when it's locked.
  - **Locked view**: name, "locked", a red banner with the date and "deleted with all its
    projects". Owners get **Cancel deletion**, others are told to ask an owner. No tabs, and no
    Rename/Leave/Delete.
  - **Delete organization** asks "Delete <org> and all its projects?". The text explains the
    immediate lock, the grace period, the owner's cancel, and the live-subscription refusal. The
    button is labeled **Request deletion**. Afterwards it stays on the page, which now shows the
    locked view, and toasts the date.
  - **Free-plan notice** (team org on `free`, owners/admins, not on the Plan tab): "<org> is on the
    Free plan (N seat), so inviting people needs an upgrade first. See plans."
  - Projects tab: locked orgs aren't offered as "Move to…" destinations.
- `components/Sidebar.tsx` — locked orgs get a "locked" badge and tooltip. After "New
  organization", a toast says it was created on the Free plan and to upgrade from its Plan tab.
- `pages/ProjectsPage.tsx` — locked-org projects render as a **Locked** card with the date and a
  link to the org, with no API calls and no Delete button.
- `pages/ProjectWorkspace.tsx` — a 423 shows "This project's organization is scheduled for
  deletion", not "We can't find this project".
- `pages/admin/AdminPages.tsx`
  - Organizations list: "Deletion requested · deletes <date>" under the name.
  - Org detail: a warning banner (requested on, deletes on, project count, only the owner can cancel)
    with **Change period** and **Delete now** (hidden for read-only support staff).
  - `DeletionDialog`: Change period takes days from now (0–3650) plus a reason. Delete now takes a
    reason and has you type the org slug to confirm, then shows a red **Delete now** button.
    After delete, the members and projects tables empty.
- `index.css` — `.sidebar-locked`.

No backend files changed. No new npm dependencies.

## Tests I wrote (TDD evidence)
The frontend has no test runner, and adding one would be a new dependency. Verification:
- **Contract check against the backend.** I ran `app.openapi()` and compared it with `api/client.ts`
  and `api/types.ts`: all 34 org/admin/account routes the UI calls exist with matching method,
  query params (`to_user_id`, audit `limit/offset`) and body fields (`{plan_id, reason}`,
  `{grace_days, reason}`, `{reason}`, `{to_slug}`, `{role}`, `{organization_id}`). The fields of 12 types
  (`Organization`, `OrgMember`, `OrgInvitation`, `OrgAuditEntry`, `AdminOrg`, `AdminOrgMember`,
  `AdminOrgProject`, `AdminSubscription`, `AdminInsights`, `PlanInfo`, `Project`, `OrgUsage`) match their API schemas
  exactly, with nothing missing on either side.
- `npx tsc -b`, `npm run lint`, `npx vite build`, backend suite: see below.

## Test run result
```
tests/api tests/unit  →  1751 passed, 2 skipped, 59 warnings in 248.80s
(unchanged from agent 2's row 4c tree — no backend files touched; skips and the Starlette 422
deprecation warnings are pre-existing. A first run reported "no tests ran" because the mounted
drive briefly listed tests/api as empty; the re-run above is the real result.)
```
Frontend: `npx tsc -b` clean. `npm run lint` shows 57 warnings, the same count as before (none in the new code). `npx vite build`
OK. E2E not run (needs Docker Compose).

## Improvement scope — out of current phase
Added to `agent-orch/backend_gaps_phase_A_to_C.md` under "Round 2 (found by agent 4, row 4d)":
- The 423 `org_deletion_pending` body doesn't say which org (no `organization_slug`), so the UI
  has to look it up.
- `GET /projects` lists projects of locked orgs, and opening any of them answers 423. Either leave
  them out or flag them (`organization_locked: true`) on `ProjectRead`.

## Open items / known issues
- **Not clicked through in a browser** (row 4d item 4). There's no database or app running on
  this machine, and starting containers plus a browser session wasn't asked for. The contract check
  above covers wiring. It doesn't cover layout or click flows. Before merge, click through:
  - create an org (Free toast and notice), invite (402 prompt), Plan → upgrade;
  - Request deletion: locked view, sidebar badge, Projects page locked card, project URL → 423 prompt;
  - Cancel deletion;
  - admin: list badge, Change period, Delete now;
  - plus row 4b's screens: accept by id, resend, People fields, Projects new/Add me/Move to,
    Audit tab, admin Billing/Insights.
- The free-plan notice keys on plan id `free`. If the owner renames that plan's id, change it there.

HANDOFF: continue at row 5 (Phase D.1) — read PLATFORM_SAAS_PLAN.md §4.2, §12.D, then agent_3.md HANDOFF, agent_2b.md and this file
