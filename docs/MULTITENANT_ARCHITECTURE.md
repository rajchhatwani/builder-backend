# Multi-tenant architecture

How Builder keeps one customer's data away from another's. This is the system description behind
SOC 2 criteria CC6 (logical access), Confidentiality and Processing Integrity; the plan it
implements is `PLATFORM_SAAS_PLAN.md` (§2–§9, §11). It describes what the code does today.

## 1. Model

- **Tenant = organization.** Every project belongs to exactly one organization
  (`projects.organization_id NOT NULL`). A solo user is an organization of kind `personal` with one
  owner; code never branches on kind.
- **Shared schema.** All tenants share one database and one set of tables, each org-scoped row
  carrying `organization_id`. One migration path, one connection pool.
- **Roles.** Organization roles `owner > admin > member`; project roles `owner > editor > viewer`.
  A person can be in several organizations with a different role in each. A person must be a member
  of a project's organization before they can be added to the project (`not_an_org_member`).
- **Platform staff** (`platform_support`, `platform_admin`) are separate accounts on a separate
  surface: their own sign-in, a different token audience (`builder-admin`), mandatory TOTP, and a
  permission table (`ADMIN_PERMISSIONS`). Customer tokens do not work on `/admin` and admin tokens do
  not work on the customer API.

## 2. Request flow: four walls

1. **Authentication.** A session token (JWT, 15 minutes, audience `builder-app`) or a hashed personal
   access token. The account is re-read from the database on every request; a token whose
   `token_version` is stale, or whose account is suspended, is refused.
2. **Resolution of the tenant.**
   - `/orgs/{slug}/…` routes use `org_context`: the slug is resolved *through the caller's own
     membership*, so a stranger and a missing org both get the same 404. The minimum org role comes from
     one flat table, `platform_authz.ORG_ROUTE_ROLES`; an unlisted route is refused.
   - Project routes use `guard`: the project's organization is looked up and the caller must be a
     member of **both** the project and its organization. Not a member → 404, never 403.
3. **Authorization.** Role needed vs. role held; API-token scopes (`read`/`write`/`generate`,
   optionally pinned to one project); org policies (require MFA, session lifetime, deletion lock).
4. **Row-level security** (below), when switched on.

Every denial is audited (`access.denied`, with the reason and no request content). Walking the real
route table keeps the first three honest: `tests/api/test_access_matrix.py` and `test_org_invariants.py`
fail if a route is reachable without a guard, an org route is missing from the role table, or a
project route resolves to no project.

## 3. Postgres row-level security (defense in depth)

The application filters by organization in SQL and re-checks in Python. RLS is a second wall: if a
handler ever forgets its filter, the database still refuses to return another tenant's rows.

**What is covered** (`app/core/rls.py`, the single source of the lists; mirrored, frozen, in
migration `f2c8a4e6b1d9`):

- `organizations` (by `id`);
- every table with an `organization_id` column: `projects`, `organization_members`,
  `organization_invitations`, `subscriptions`, `sso_connections`, `sso_domains`,
  `sso_login_requests`, `scim_directories`, `scim_users`, `scim_groups`, `impersonation_sessions`;
- `platform_audit_log` (rows with no organization, i.e. platform-level events, stay visible and
  writable so sign-in failures can still be recorded);
- every table that belongs to a project (`entities`, `relations`, `project_roles`,
  `project_permissions`, `project_members`, `generations`, the per-project config and secrets tables,
  `auth_custom_fields`): a row is visible exactly when its project is.

A test (`test_the_policy_lists_cover_every_table_with_an_org_column`) fails when a new table with an
`organization_id` or a non-null `project_id` is not in the list.

**How it works.** Policy `tenant_isolation` on each table:

```sql
USING (nullif(current_setting('app.organization_id', true), '') IS NULL
       OR organization_id = nullif(current_setting('app.organization_id', true), '')::uuid)
```

`guard` and `org_context` call `rls.bind(db, organization_id)` immediately after the caller's
membership in that organization has been proved. It runs
`SELECT set_config('app.organization_id', :org, true)` - i.e. **`SET LOCAL`**: the value dies with
the transaction, so a pooled connection never carries one request's tenant into the next. A
SQLAlchemy `after_begin` hook re-applies it at the start of every later transaction of the same
request (a handler that commits and carries on stays confined). The middleware clears the context
variable at the end of every request.

**Unscoped requests are not confined.** When `app.organization_id` is unset the policy lets every row
through. That is deliberate and the reason RLS can be rolled out without a flag day: sign-in, SSO
callbacks, Stripe webhooks, SCIM, the operator console and background jobs legitimately span
organizations and run unscoped, exactly as before. RLS therefore protects the *org-scoped request
paths*, which is where a missing `WHERE organization_id = …` would leak. A stricter "deny when unset,
every platform path declares itself" mode is a possible later step (see §8).

**The one legitimate cross-org write.** Moving a project to another organization reads and writes
two tenants, so that handler calls `rls.release(db)` first (the caller was already authorised as owner of
the source, and the service re-checks the destination).

**Table owner and superusers.** The policies are created with `FORCE ROW LEVEL SECURITY`, so the table
owner is bound too. A Postgres superuser (and any role with `BYPASSRLS`) always bypasses RLS; the
application role must be neither. We never grant `BYPASSRLS` to it - only migration/ops roles.

### Three separate switches

| Switch | Effect | Default |
|---|---|---|
| Migration `f2c8a4e6b1d9` | Creates the policies. Inert until a table has RLS enabled. | applied |
| `python -m app.core.rls enable --yes` | `ENABLE` + `FORCE ROW LEVEL SECURITY` on every table (`disable` reverses it; `status` shows state). | **not run** |
| `BUILDER_RLS_ENABLED=true` | Requests bind `app.organization_id`. With RLS not enabled on the tables nothing changes. | **false** |

### Local development setup

The compose database user is a superuser, which ignores RLS, so the app must connect as a restricted role.
Create `builder_app` (`LOGIN NOSUPERUSER NOBYPASSRLS`), grant it DML on all tables and sequences plus default
privileges for the owner, put `BUILDER_DATABASE_URL=postgresql+asyncpg://builder_app:…@localhost:5432/builder` and
`BUILDER_RLS_ENABLED=true` in `.env`, run migrations with the owner URL, then `python -m app.core.rls enable --yes`.
The full SQL and the reasoning are in `platform_implementation_agents/agent_11.md`, section A of the follow-up.

### Rollout (needs a decision from the owner each time)

1. Staging, with a **non-superuser, non-`BYPASSRLS` application role**: set
   `BUILDER_RLS_ENABLED=true`, run `python -m app.core.rls enable --yes`, then run the whole test suite
   and the load test. The repository's tests exercise the policies with a policy-bound role
   (`tests/api/test_rls.py`), including a handler that deliberately forgets its filter.
2. Compare p95 latency before and after. The project-child policies add a semi-join on
   `projects.id` (primary key) to each child query.
3. Production: enable the flag first (harmless), then `enable --yes` in a quiet window. Rollback is
   `python -m app.core.rls disable` (instant, no data change) and/or the flag.
4. Watch `access.denied` and 5xx for "row-level security policy" errors in the first hours.

## 4. Secrets and what the operator cannot see (plan §7.1)

- Project credentials (SMTP/SMS keys), SSO client secrets and similar are encrypted with a key held in
  the application environment (`app/core/crypto.py`); the `/admin` role has no route that decrypts
  them. Personal and SCIM tokens, invitation tokens and recovery codes are stored only as hashes and
  shown once. Passwords use scrypt. TOTP secrets are encrypted.
- Admin schemas carry no spec content, no credentials and no `detail` of customer data. The audit
  `detail` sanitizer drops any key containing `password`, `token`, `secret`, `authorization`,
  `cookie` or `otp`.
- `tests/api/test_operator_secrets.py` plants a canary in every secret type, then walks **every**
  `/admin` read route - and every route a "view as" token can reach - and fails if a canary appears.
  Because the route list is read from the app, new routes are covered automatically.
- Operators cannot rotate a customer's SCIM token *and* see it: the operator rotation installs a
  token nobody ever sees and switches SCIM off; an org admin then generates their own.

## 5. Impersonation ("view as")

For support. Designed so a customer can quote it in a security questionnaire.

- **Consent.** Per-organization policy *Allow platform support to view as members*
  (Organization → Security). **Default on**; an enterprise org turns it off, and operators then cannot
  start a session. Turning it off ends running sessions immediately (`impersonation.ended`,
  `why: consent_withdrawn`).
- **Who.** Only a `platform_admin` (permission `impersonate:write`), only for an *active, non-staff
  member of that organization*, with a written reason (5–200 characters).
- **What the token is.** A 10-minute customer-audience JWT for that member with claims `imp_sid`
  (session id) and `imp_by` (operator). The session row in `impersonation_sessions` is the authority and is
  re-read on every request: session ended or expired, operator suspended or demoted, member removed, or
  consent withdrawn → the token stops working at once. The token is returned once, never stored, never
  logged, never in any listing.
- **Scope.** One organization. Other orgs and projects answer 404; `GET /orgs` and `GET /projects` are
  cut to that org. Account routes (password, MFA, tokens, default org, logout-all) refuse it
  (`session_required` / `impersonation_blocked`), as do invitation acceptance and org creation.
- **Read-only by default.** Writes need the viewer-side switch (*Allow changes for 5 minutes*), which is
  audited both ways and times out. Even with writes on, a viewing token can never: touch API/MCP
  tokens, project auth secrets, billing, the org export, or generation downloads; create or delete a
  project; change project membership; or change anything under `/orgs/{slug}` (the org console is
  look-only).
- **Trail.** Every request is audited with `via = "impersonation"`, the viewed member as actor and
  `impersonator_id` in the detail (`impersonation.request`, `project.change`, `impersonation.denied`).
  These events carry the organization id, so the customer sees them in **their own** audit log.
- **Banner.** The app shows a persistent "You are viewing as X (operator Y)" bar with an *Allow
  changes* switch and *Exit*.
- **Daily digest.** `python -m app.jobs.impersonation_digest` (cron or any timer; `--dry-run`, `--force`)
  posts every session of the last 24 h - who, as whom, which org, the reason, until when, read-only or
  how many changes - to a Slack-compatible webhook (`BUILDER_SECURITY_DIGEST_WEBHOOK_URL`) and/or an
  e-mail address (`BUILDER_SECURITY_DIGEST_EMAIL`, uses the SMTP settings), plus how many attempts were
  refused because an org had turned support access off. A quiet day still sends a message, so silence
  means the job is broken. A re-run within the day is skipped; exit code 1 = no destination, 2 = delivery
  failed. Delivery is audited (`impersonation.digest_sent`; the URL is never logged). Preview:
  `GET /admin/impersonation/digest`.

## 6. Per-org data export

`GET /orgs/{slug}/export` returns one JSON file (`builder-org-export/1`): the organization and its
policies, plan and status, members, invitations, every project with its assembled spec and members,
SSO and SCIM status (never certificates, secrets or the bearer), and the organization's audit trail.
Owners only, from a signed-in session (not API tokens, not operators, not "view as"); allowed while an
org is scheduled for deletion so data can be taken out first. Each export is audited (`org.exported`,
counts only). Never in the file: password hashes, TOTP secrets, recovery codes, any token or hash,
Stripe ids, IdP certificates, project credentials.

This is the unit for Processing Integrity and for "right to be forgotten" workflows: export, then
the owner's deletion request (grace period, then the organization and all its projects are deleted).
Backups are cluster-wide; erasure from backups follows the backup retention window.

## 7. Logging and audit

- Structured logs bind `organization_id` and `request_id` for every org-scoped request.
- `platform_audit_log` is append-only (a trigger rejects `UPDATE` and `DELETE`) and has no foreign
  keys, so rows outlive users and projects. `GET /orgs/{slug}/audit` always filters by the caller's
  organization; the operator audit can filter by organization.

## 8. Known limits and next steps

- RLS does not confine unscoped paths (§3). A deny-by-default mode with explicit per-path declarations
  is the next step once the flag has run in production.
- `fields` has no direct project column (reached through `entities`) and `platform_api_tokens` has an
  optional project; neither has a policy yet.
- No per-organization encryption keys (one application key). Moving to a per-org data key is possible
  without schema change to callers.
- Database defaults/CHECKs on some org tables are enforced in code only.
- See `docs/PENTEST_PLAN.md` and `docs/SOC2_EVIDENCE.md` for assurance activities.
