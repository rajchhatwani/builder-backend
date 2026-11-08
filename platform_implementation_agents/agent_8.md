# Agent 8 report — claude-opus-5-5 — 2026-10-27

## Scope accepted
Queue row 8: Phase E, SCIM 2.0 (§4.3, §12.E). While I worked, the owner asked me to hand the UI to a
frontend agent once the backend was done. So I **split row 8**: row 8 is the backend (this
report), and a new **row 9** is the SCIM frontend. Its full spec is in
**`agent-orch/frontend_scim_phase_E.md`**. Phase F is now row 10.

Baseline before changes: `tests/api tests/unit` → **1916 passed, 2 skipped**.

## What was already done
- Rows 1–7: orgs, plans/quotas (`plans.allow_scim` seeded, true on `enterprise` only), Stripe, org
  console, deletion requests, SSO (verified domains in `sso_domains`), MFA, policies, and their UI.
- Nothing for SCIM existed.

## Research notes / decisions
- **Wire format** follows RFC 7643/7644, with the quirks of the big IdPs (§12.E.6):
  - Okta sends a path-less `replace` with `{"active": false}`.
  - Entra ID capitalises ops (`Replace`), sends `"False"` strings, and uses
    `emails[type eq "work"].value` paths, `members` Add/Remove and `excludedAttributes=members`.
  - JumpCloud and Google Workspace send PUT-style full bodies.
  - Supported filters: `eq` on `userName`, `externalId`, `emails.value` and `id` (Users), and on
    `displayName`, `externalId` and `id` (Groups). Anything else is a 400 `invalidFilter`, not
    silently ignored.
  - Bulk, sort and ETags are off, and `ServiceProviderConfig` says so.
- **Tenant from the token** (§12.E.2): `bb_scim_<random>`, stored only as SHA-256 and shown once,
  with its last 4 characters as a hint. The org is never taken from the URL. Every lookup is scoped
  to the token's org, and group member ids from another org are ignored.
- **Who can be provisioned:** only addresses on a domain *this* org verified in DNS. This is the
  rule SSO already uses, and the domains are the same ones (`sso_domains`). It means one org can't
  provision, rename or offboard another org's people. Platform staff are refused. An existing
  account on the domain is **linked**, not duplicated, and keeps its password.
- **New accounts are SSO-only** (`!sso-only` password hash): the platform has no password reset,
  and SCIM is enterprise, so it comes with SSO. Each new account gets its personal org, as JIT
  accounts do.
- **`userName` names the account e-mail** when it looks like one (Okta login and Entra UPN both
  do); otherwise the primary work e-mail is used. A rename must stay on a verified domain and must
  not collide with another account (409).
- **Seats (§6.2 "SCIM create"):** creating or reactivating a user goes through
  `enforce_seat_limit` (402 path, `quota.denied` audited), answered as SCIM 403 with the message.
  `BillingService.sync_seats` runs after the commit (agent 3's note). Inactive users take no seat.
- **Offboarding (`active: false` / DELETE):**
  - What goes: the org membership, the person's project memberships in this org, and API tokens
    pinned to this org's projects. All sessions are revoked and `token_version` is bumped, so the
    person is **signed out everywhere**, as §4.3 says.
  - What stays: unpinned PATs (they lost the org with the membership), the personal org, other
    orgs, and the account itself.
  - The SCIM user stays, so the IdP can read and reactivate it. DELETE removes it too.
  - Projects the person owned alone are **handed to an org owner** (the earliest-joined one),
    audited as `scim.project_handed_over`. The normal remove-member path would have refused
    (`sole_project_owner`), which would make IdP offboarding fail.
  - The **last org owner** can't be offboarded: SCIM 409 `mutability`, and nothing changes.
- **Group → role dictionary (§12.E.3):**
  - It lives on `scim_directories.group_roles` (lower-cased group name → `owner|admin|member`).
  - Empty means groups don't touch roles, and SCIM users join as members.
  - Otherwise each SCIM-managed person gets the highest mapped role among their groups, or member.
  - Roles are recomputed on every group change and when the dictionary changes.
  - The directory never demotes the last owner.
  - Only an org **owner** may add an `owner` mapping or change a dictionary that has one (§2.2:
    admins can't make owners).
- **Operator rotation (§12.E.4):** `POST /admin/organizations/{id}/scim/rotate {reason}`, for
  platform admins only.
  - It replaces the token with one **nobody ever sees** (§7.1: operators don't see customer
    secrets) and switches the directory off. An org admin then issues a fresh one, which switches the
    directory back on (follow-up from agent 9). An admin's own "off" is kept when they rotate.
  - This is my reading of "bearer-token rotation" for operators. A rotation that showed the token
    to the operator would let staff provision people into a customer org.
- **Gates:** a downgraded plan or an org locked for deletion → SCIM 403. A switched-off or removed
  directory → 401. Failed bearer attempts count against the sign-in rate limiter (429).
- **No new dependencies.** No new settings: the base URL is `BUILDER_PUBLIC_API_URL` + `/scim/v2`.

## Implementation summary
- `alembic/versions/a9c4e2f7b1d3_scim_directories.py`, the **new Alembic head** (after
  `f5c3a8e1b7d9`):
  - `scim_directories`: §3.1 plus `token_hint`, `token_created_at`, `group_roles`, `created_by`;
  - `scim_users`: unique (org, account) and (org, lower(userName));
  - `scim_groups`: unique (org, lower(displayName));
  - `scim_group_members`.
  - It downgrades cleanly.
- `app/models/scim.py`, registered in `app/models/__init__.py`.
- `app/services/scim_protocol.py` (new, pure): filters, PATCH for users and groups, payload
  parsing, resources, ListResponse, ServiceProviderConfig / ResourceTypes / Schemas, and
  `ScimError`.
- `app/services/scim_service.py` (new): setup (issue/rotate, update, delete, operator rotate,
  summary), bearer authentication, Users and Groups CRUD, join/leave, project handover, role sync,
  and `scim.*` audit with `via="scim"`. It never audits tokens.
- `app/api/scim.py` (new):
  - `/scim/v2` routes with the `scim_auth` dependency;
  - `application/scim+json` responses with `Location` on create;
  - the org setup routes `GET|PATCH|DELETE /orgs/{slug}/scim` and `POST /orgs/{slug}/scim/token`,
    session only.
- `app/schemas/scim.py` (new): `ScimConfigRead`, `ScimTokenRead`, `ScimConfigUpdate`.
- `app/main.py`: both routers, plus a `ScimError` exception handler (SCIM error JSON, and
  `WWW-Authenticate` on 401).
- `app/core/platform_authz.py`: the 4 org routes added to `ORG_ROUTE_ROLES` (admin).
- `app/api/admin.py`, `app/services/admin_service.py`, `app/schemas/account.py`:
  - `AdminOrgRead.scim_configured / scim_active / scim_users / scim_last_sync_at /
    scim_token_created_at` (`org_scim()`);
  - the rotate route.
- `tests/api/test_access_matrix.py`: the route walker accepts `scim_auth` as a guard. The
  unauthenticated sweep covers SCIM (401).

## Tests I wrote (TDD: red first, then green)
- `tests/unit/test_scim_protocol.py` (34): filters (case, escaping, unsupported), booleans, Okta,
  Entra and JumpCloud payloads, user and group PATCH (no-path, dotted keys, member filters,
  read-only attributes), error and list shapes, paging, discovery.
- `tests/api/test_scim.py` (27):
  - setup: plan gate + `quota.denied`, personal org, token shown once / hash only / not audited,
    rotation, on/off/remove, admin + session only, owner-only owner mapping;
  - protocol: 401 shape, discovery, plan downgrade / deletion lock, last sync;
  - users: create (SSO-only, personal org, seat sync, filters), duplicates / foreign domain / staff
    / malformed JSON, linking an existing account, seat cap, PUT/PATCH incl. renames, offboarding
    (memberships, tokens, sessions, project handover, reactivation), API access cut, last owner,
    DELETE, paging;
  - tenant isolation;
  - groups CRUD in Entra and Okta shapes, role mapping, last-owner guard;
  - operator status + rotation (support refused, the token never shown).
- `tests/api/test_migrations.py` (+1): tables, defaults, unique indexes, round trip.
- **Mutation checks** (each mutant must turn the suite red), all **caught**:
  - no verified-domain check;
  - user lookups not scoped to the org;
  - group lookups not scoped to the org;
  - groups accepting another org's users;
  - last owner offboardable;
  - last owner demotable;
  - no sign-out on deactivation;
  - staff provisionable;
  - switched-off directory still accepted;
  - no project handover.

## Test run result
`uv run pytest tests/api tests/unit -q` → **1978 passed, 2 skipped, 63 warnings in 245s** (baseline
1916 → +62 new). The affected files were re-run after lint fixes: 128 passed.
- ruff check/format: clean on every file I touched.
- mypy: clean on the SCIM modules. The errors it reports are in `security.py:270` and
  `stripe_client.py`, and predate this row.
- Frontend not touched (row 9). `tests/e2e` not run (needs Docker Compose).

## Improvement scope — out of current phase
- **Not checked against a real IdP.** The payloads follow the documented shapes of Okta, Entra ID,
  JumpCloud and Google. The first deploy should run Okta's SCIM test suite (Runscope/CRUD) and
  Microsoft's SCIM Validator against a staging URL. Until then, the §12.E.6 compatibility
  checklist is only "designed for".
- Filters beyond `eq` (`and`, `co`, `sw`, `meta.lastModified gt`), `attributes=` projection, bulk,
  and ETags are not supported.
- `OrganizationMemberRead` doesn't say who is SCIM-managed. A "SCIM" badge on People would need
  that field.
- Deleting a SCIM user keeps the Builder account. Erasure ("right to be forgotten", §4.3) belongs
  with Phase F's per-org export / GDPR work.
- A per-directory rate limit (not per IP) and a background job for large group pushes, if a big
  tenant needs them.
- "Enforce SSO" for the domain is still not in the plan (agents 5–6 noted it). Without it, a
  linked account that had a password keeps that password.

## Open items / known issues
- **Owner decision noted, not asked:** deactivation signs the person out **everywhere**, including
  their personal org, because §4.3 says so literally. If the owner prefers "only this org", the
  `revoke_all_sessions` call in `ScimService._leave` is the one line to drop. Membership removal
  already cuts the org off.
- Accounts SCIM creates can only sign in through the org's SSO. An org running SCIM without SSO
  gets members who can't sign in. The UI checklist (row 9) should say so.

## HANDOFF: continue at row 9 — frontend for SCIM (Phase E UI) — read `agent-orch/frontend_scim_phase_E.md` first
