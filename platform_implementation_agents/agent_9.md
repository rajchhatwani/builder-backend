# Agent 9 report — claude-opus-5-5 — 2026-10-27

## Scope accepted
Queue row 9: frontend for row 8 (Phase E SCIM UI), frontend only. The spec is
`agent-orch/frontend_scim_phase_E.md`: P0 customer setup, P1 operator console + audit, P2 notes.
No backend changes.

I waited for agent 8 (another session running in this tree) to tick row 8 and write its `HANDOFF:`
line before touching anything. Baseline before changes: `tests/api tests/unit` → **1978 passed,
2 skipped**.

## What was already done
- SCIM backend (agent 8, `agent_8.md`):
  - `app/api/scim.py`: the `/scim/v2` routes, plus `GET|PATCH|DELETE /orgs/{slug}/scim` and
    `POST /orgs/{slug}/scim/token`;
  - `POST /admin/organizations/{id}/scim/rotate`;
  - `AdminOrgRead.scim_*`.
- SSO tab, `Copyable`, `RecoveryCodes` show-once pattern, `AskAdmin`, global 402 `QuotaPrompt`, admin
  `SsoStatus` / "Single sign-on and security" card / audit group filter (agents 4 and 7).

## Research notes / decisions
- **Types checked against the live OpenAPI** (`/openapi.json`, `BUILDER_ENVIRONMENT=local`):
  `ScimConfigRead`, `ScimTokenRead`, `ScimConfigUpdate`, `ScimGroupSummary`, the 4 org routes, the
  rotate route + `AdminReason`, and the 5 `AdminOrgRead.scim_*` fields. All match.
- **The token is shown inline, not in a modal.** The native `<dialog>` closes on Esc, which would
  drop the token before it's saved. It lives only in the section's state. It's cleared on "Done"
  (enabled once "I saved the token" is ticked), on Remove, and on leaving the page. It never goes to
  storage; the click-through checks localStorage/sessionStorage.
- **After an operator rotation** (`token_hint` null) the page explains that support replaced the
  token, offers **Generate a new token**, and hides Turn on.
  - Found while clicking through: the backend's `issue_token` only switched SCIM on when it
    *created* the directory, so a new token after an operator rotation stayed **off**.
  - **Resolved (agent 8, 2026-10-27):** not intended. A fresh token after an operator rotation
    now switches SCIM back on; an admin's own "off" is still kept on rotation. The banner and the
    operator dialog say so.
- **Group mapping editor** sends the whole dictionary, with names trimmed and lower-cased.
  - The pushed groups are offered as suggestions (`<datalist>`), and free text is allowed.
  - Duplicates are compared without case. They're warned about and block Save.
  - "Add mapping" stops at 100.
  - Non-owners: the `owner` option is hidden. If the dictionary already contains an `owner`
    mapping, the editor is read-only with the owner-only explanation.
  - A 403 `org_role_required` with `needed_role: owner` gets the same text, in case the state
    changed underneath.
- **QuotaPrompt** gains the `scim` label ("SCIM provisioning"). It also gains wording for
  `reason: "feature"`: "The free plan doesn't include SCIM provisioning". Before, a feature refusal
  read "includes 0 single sign-on". The SSO 402 benefits too.
- **Tab renamed** "SSO" → "SSO & SCIM" (plan §8.1).
- The "Connect your identity provider" checklist reuses data the SSO tab already loaded (verified
  domains, SSO on). It doesn't need a new call. It says that SCIM-created accounts have no password
  and sign in through SSO (agent 8's open item).

## Implementation summary
- `frontend/src/api/types.ts`:
  - `ScimRole`, `ScimGroupSummary`, `ScimConfig`, `ScimToken`, `ScimConfigUpdate`;
  - `QuotaDetail.resource` adds `'scim'`;
  - `AdminOrg.scim_configured / scim_active / scim_users / scim_last_sync_at /
    scim_token_created_at`.
- `frontend/src/api/client.ts`: `scimConfig`, `issueScimToken`, `updateScim`, `deleteScim`,
  `adminRotateScim`.
- `frontend/src/components/Copyable.tsx` (new): moved out of `OrgSsoTab.tsx` so both sections
  share it.
- `frontend/src/pages/OrgScimSection.tsx` (new), the P0 section:
  - status (on/off/not set up, last sync or "The IdP hasn't connected yet", active/deactivated
    counts, token age + `bb_scim_…abcd` hint);
  - Generate / Rotate (confirm) / Generate a new token;
  - show-once token;
  - Turn on/off (confirm on off);
  - Remove SCIM (danger confirm);
  - setup checklist + Base URL / Users URL copy rows;
  - group table (pushed groups, members, mapped role) + mapping editor;
  - plan upgrade notice;
  - readable errors (`scim_not_for_personal_orgs`, `scim_not_configured`, `session_required`,
    owner-only 403, 422).
- `frontend/src/pages/OrgSsoTab.tsx`: renders the SCIM section below the SSO sections. The Domains
  card gets `id="sso-domains"`, which the checklist scrolls to. The members' ask-your-admin text
  mentions SCIM.
- `frontend/src/pages/OrgConsole.tsx`:
  - tab label "SSO & SCIM";
  - org audit "who" shows **SCIM** for IdP rows;
  - P2: one line of help under People ("If your identity provider maps groups to roles (SCIM),
    its next sync can change a role you set here").
- `frontend/src/components/QuotaPrompt.tsx`: the `scim` label and the feature-refusal wording.
- `frontend/src/pages/admin/AdminPages.tsx`:
  - `ScimStatus` + a **SCIM** column ("on · 12 users" / "off" / "—", last sync in the tooltip).
  - Org detail card: SCIM status, last sync, token age, and **Rotate SCIM token**.
    - The button is hidden for support (`readOnly`).
    - `RotateScimDialog`: a danger dialog with a required reason and the §7.1 wording.
    - After a rotation the org and the audit tail refresh.
  - Audit: `scim.` event group and `scim` source options.
  - `auditActor()` shows "SCIM" for actor-less `via=scim` rows, in the audit page and in the org
    audit tail.
- No new dependencies. No backend changes.

## Tests / verification
The frontend still has no test runner (agent 7 noted this), so red → green in the frontend wasn't
possible. Instead I clicked every flow in **headless Chrome** (puppeteer-core) against a throwaway
stack:
- Postgres 16 in Docker, `alembic upgrade head` (head `a9c4e2f7b1d3`);
- uvicorn and Vite dev;
- seeded: owner Alice, admin Bob, member Carol; team org `acme` on enterprise with `acme.test`
  verified via SQL; team org `freeco` on free; the bootstrap operator, whose TOTP the script enrols;
- the IdP side driven with real SCIM calls.

The driver and screenshots live in the session scratchpad. puppeteer-core was installed there,
**not** in the repo.

**63/63 checks pass**:
- **Setup:**
  - "not set up", URLs, checklist states;
  - Generate → token shown once, Done locked until ticked, token gone after Done, nothing in
    storage, hint shown;
  - Rotate asks to confirm; the new token works and the old one gets 401.
- **IdP sync:**
  - a user and a group pushed with the token;
  - the page then shows last sync, "1 active user · 0 deactivated", and the group as "not mapped".
- **Mapping:**
  - the owner sees Owner;
  - "Builder Admins → Admin" saved lower-cased, and Dave was really promoted (DB);
  - duplicates warned with Save disabled.
- **On/off:** the IdP gets 401 while off.
- **Admin Bob:**
  - no Owner option;
  - with an Owner mapping: notice shown, editor read-only, no Save/Add;
  - the API answers 403 `org_role_required` with `needed_role: owner`.
- **Member Carol:** ask-your-admin.
- **Plan:**
  - the free org shows the upgrade notice, and Generate is disabled;
  - on a downgraded org, Rotate → 402 → "doesn't include SCIM provisioning" prompt.
- **Operator:**
  - list column "on · 1 user", "—" for no SCIM, tooltip;
  - detail status, last sync and token age;
  - the rotate dialog's §7.1 wording, and the reason is required;
  - after the rotation: off, no token on the page, `admin.scim_token_rotated` in the tail, the
    IdP token dead;
  - audit `scim.` and source `scim` filters, with "SCIM" as the actor.
- **Owner after the operator rotation:**
  - explanation shown, "Generate a new token", no Turn on;
  - the new token was refused until Turn on (since fixed in the backend: it now works at once;
    the click-through was not re-run).
- **Org audit:** "SCIM" as the actor. **People:** help line shown.
- **Remove SCIM:** back to "not set up"; Dave is still a member.
- **Phone width (390 px):** no horizontal scroll.

**Only type-checked, not clicked:**
- the 422 message (the UI prevents empty and duplicate names);
- 409 `scim_not_for_personal_orgs` (the tab is hidden for personal orgs);
- support staff not seeing Rotate SCIM token (same `readOnly` flag as every other admin action).

## Test run result
- `uv run pytest tests/api tests/unit -q` → **1978 passed, 2 skipped** (no backend changes; same as
  the baseline).
- `npx tsc -b` clean. `npx vite build` OK (only the existing >500 kB chunk warning).
  `npm run lint` → **57 warnings, 0 errors, unchanged**; none are in files or lines I touched.
- `tests/e2e` not run (it needs Docker Compose).

## Improvement scope — out of current phase
- People "SCIM" badge: `OrganizationMemberRead` doesn't say who is SCIM-managed (agent 8 noted
  this). The help line is the stand-in.
- The org audit tab has no event-group filter; the backend `GET /orgs/{slug}/audit` has no action
  filter to drive one.
- The frontend test runner (Vitest + Testing Library) is still missing. It's a new dev dependency,
  so it's the owner's call (agent 7 noted the same).

## Open items / known issues
- Not checked against a real IdP (Okta / Entra / JumpCloud / Google). The pages were driven by
  plain SCIM calls in the documented shapes (agent 8's open item still stands).
- Not committed (the owner asked for no commits).

## HANDOFF: continue at row 10 — Phase F (code): RLS behind a flag, impersonation, per-org export, docs — read PLATFORM_SAAS_PLAN.md §3.3, §4.5, §9, §11, §12.F, then agent_8.md and this report
