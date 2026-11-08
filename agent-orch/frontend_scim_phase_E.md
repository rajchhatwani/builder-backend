# Frontend for Phase E (SCIM 2.0) — handoff from agent 8 to agent 9

The SCIM backend is done (row 8, report `platform_implementation_agents/agent_8.md`). Row 9 builds
**only the UI** below: no backend changes. Check every type against the live OpenAPI
(`/openapi.json` with `BUILDER_ENVIRONMENT=local`) before wiring it.

Plan refs: §4.3, §7 (operator console), §8 "SSO & SCIM", §8.1 (`#/org/<slug>/sso` = SSO & SCIM),
§12.E.4–5.

## P0 — customer SCIM setup (`#/org/<slug>/sso`, a new "SCIM provisioning" section)

Put it in `frontend/src/pages/OrgSsoTab.tsx` below the SSO sections (plan §8: one page for "SSO &
SCIM"). It's for team orgs only; the tab is already hidden for personal orgs.

### Endpoints (org admins; a signed-in session is required, and API tokens get 403 `session_required`)

| Call | Body | Answer |
|------|------|--------|
| `GET /orgs/{slug}/scim` | — | `ScimConfigRead` |
| `POST /orgs/{slug}/scim/token` | — | `ScimTokenRead`: **201** when it creates the directory (it starts **on**), **200** when it rotates the token. The old token stops working at once. |
| `PATCH /orgs/{slug}/scim` | `{active?: bool, group_roles?: {[group]: "owner"\|"admin"\|"member"}}` | `ScimConfigRead` |
| `DELETE /orgs/{slug}/scim` | — | 204. Removes the directory and its users/groups records; **org memberships stay**. |

`ScimConfigRead`:
```ts
{
  configured: boolean; allowed_by_plan: boolean; active: boolean;
  base_url: string;            // paste into the IdP as the SCIM base / tenant URL
  users_url: string;           // base_url + "/Users" (some IdPs ask for this)
  token_hint: string | null;   // last 4 chars, show as "bb_scim_…abcd"; null after an operator rotation
  token_created_at: string | null; created_at: string | null; last_sync_at: string | null;
  group_roles: Record<string, string>;   // keys are lower-cased group names
  active_users: number; deactivated_users: number;
  groups: { display_name: string; members: number; mapped_role: string | null }[];
}
```
`ScimTokenRead` = `ScimConfigRead` + `token: string`. **Show the token once**: same "copy it now,
then tick I saved it" pattern as `RecoveryCodes` in `components/MfaStep.tsx`. Never keep it in
state after the dialog closes, and never put it in `localStorage`.

### Errors to explain
- **402 `scim_not_in_plan`** (`details[0].resource = "scim"`, `reason = "feature"`): the global
  `QuotaPrompt` already opens. Add the label "SCIM provisioning" for resource `scim`
  (next to "single sign-on" in `QuotaPrompt.tsx`), and extend `QuotaDetail.resource` with `'scim'`.
  When `allowed_by_plan` is false, show the same upgrade notice the SSO section shows.
- 409 `scim_not_for_personal_orgs`; 409 `scim_not_configured` (PATCH/DELETE before a token exists).
- 403 `org_role_required` with `details[0].needed_role = "owner"`: only an **owner** may map a group
  to `owner`, or change a dictionary that already contains one. Admins can map `admin` / `member`.
  Hide the `owner` option for non-owners (`OrgSummary.role`), and still handle the 403.
- 422: unknown role, empty group name, or more than 100 mappings.
- Members (not admins): read-only, with `AskAdmin` (the GET answers 403 `org_role_required`).

### What the section shows
1. Status: Off / On, "Last sync <time>" (null = "The IdP hasn't connected yet"), active and
   deactivated user counts.
2. **Generate token** (not configured) or **Rotate token** (configured). Rotating needs
   `useUi().confirm`: "The current token stops working immediately. Update your IdP right away."
3. Copy rows (`Copyable` in the same file) for `base_url`, `users_url`, and the token while it's
   shown.
4. On / off toggle (`PATCH {active}`). Turning it **on** after an operator rotation does nothing
   useful until a new token exists: the token is unknown to everyone. So when `token_hint` is
   null, offer "Generate a new token" instead.
5. **Group → role mapping** editor. Rows of group name + role select. Offer the names in `groups`
   (what the IdP pushed) as suggestions, and allow free text (a group can be mapped before it's
   pushed). Save sends the **whole** dictionary. Explain the rules in one line: "People in mapped
   groups get the highest mapped role; everyone else provisioned by SCIM is a Member. With no
   mappings, SCIM doesn't change roles." Show each group's `mapped_role` and member count.
6. **Remove SCIM** (danger confirm): "People stay in the organization; the IdP can't sync any
   more."
7. A short setup checklist: verify a domain first (people can only be provisioned on the org's
   **verified domains**, the same domains as SSO, so link to the domains section above). Then
   paste the base URL and token into Okta / Entra ID / JumpCloud / Google Workspace. Provisioned
   accounts sign in **through SSO** (they have no password).

## P1 — operator console (`frontend/src/pages/admin/AdminPages.tsx`)

`AdminOrgRead` has new fields:
```ts
scim_configured: boolean; scim_active: boolean; scim_users: number;
scim_last_sync_at: string | null; scim_token_created_at: string | null;
```
- Organizations list: a **SCIM** column next to the SSO one (`SsoStatus`): "on · 12 users",
  "off", or "—". Put the last sync in the tooltip.
- Org detail, in the "Single sign-on and security" card: SCIM status, last sync, token age, and a
  **Rotate SCIM token** button.
  - It calls `POST /admin/organizations/{id}/scim/rotate {reason}` and returns `AdminOrgRead`.
  - Platform **admins** only (`users:write`); support gets 403, so hide the button for support.
  - Danger confirm with a required reason. Say plainly: "The new token is not shown to anyone. SCIM
    is switched off until an org admin generates a token." That is §7.1: operators never see
    customer secrets.
  - 404 when the org doesn't exist.
- Audit: add a **`scim.`** option to the action-group `<select>` (next to `sso.`). The new events
  are:
  - `scim.directory_created|token_rotated|directory_updated|directory_deleted`
  - `scim.user_created|user_updated|user_email_changed|user_deactivated|user_reactivated|user_deleted`
  - `scim.group_created|group_updated|group_deleted`
  - `scim.role_changed`, `scim.project_handed_over`
  - `admin.scim_token_rotated`

  Audit rows written by the IdP have `via = "scim"` and no actor, so show "SCIM" as the actor.
  The org audit tab (`#/org/<slug>/audit`) gets the same `scim.` option if it has a group filter.

## P2
- People tab (`OrgConsole.tsx`): nothing new is required. A "SCIM" badge on provisioned members
  would need a backend field (`OrganizationMemberRead` doesn't say who is SCIM-managed). Note it
  as a gap rather than guessing.
- Org People: when an admin changes the role of someone in a mapped group, the next group push
  from the IdP can change it back. One line of help text near the role select is enough.

## Gate
`npx tsc -b`, `npm run lint` (no new warnings over 57), `npx vite build`. The backend suite stays
green (see `agent_8.md` for the count). The SCIM endpoints can be driven with plain `curl` and the
token to fill the page with users and groups:
```sh
T=bb_scim_...; B=http://localhost:8000/scim/v2
curl -s -H "Authorization: Bearer $T" -H 'Content-Type: application/scim+json' \
  -d '{"userName":"alice@acme.test","name":{"givenName":"Alice","familyName":"Smith"}}' $B/Users
curl -s -H "Authorization: Bearer $T" -H 'Content-Type: application/scim+json' \
  -d '{"displayName":"Builder Admins","members":[{"value":"<id from above>"}]}' $B/Groups
```
The domain must be verified first: set `sso_domains.verified_at` with SQL locally, as agent 7 did.
Write `platform_implementation_agents/agent_9.md`, tick row 9, and hand off to row 10 (Phase F).
