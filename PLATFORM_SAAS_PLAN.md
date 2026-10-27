# Platform SaaS Plan: Organizations, Enterprise SSO, Plans & Seats

**Status:** design / planning. No code written yet. This document is the shared target so we can
build it in deliberate phases.

**Scope.** Right now Backend Builder is a single-level product: a `PlatformUser` with 0‑N
`Project`s, plus a `/admin` console for your own operators. There is **no notion of a customer
organization**, no customer-side "admin" surface, no SSO, no plan or quota ceiling. This document
designs that layer: how an onboarded customer (individual **or** organization) manages its own
people, how enterprise customers bring their own identity provider, how your operator console sees
and gates everything, and how we enforce plan limits on resources (seats, projects, MCP tokens,
etc.) without pointing a shotgun at our runway.

**Key words.** "Platform" = Backend Builder (you). "Operator" = your staff running the platform.
"Customer" or "tenant" = the organization or individual you onboarded. "Member" = a human in a
customer org. "Project" is unchanged — the thing that generates a backend.

---

## 1. Vision

Think of the platform as three concentric surfaces, each with its own sign-in audience and its
own clear authority:

```
┌─ Platform operator console  (/admin)        ─ your staff
│    sees:   every org, every user, plans, billing status, audit, impersonation
│    cannot: open customer specs or decrypted credentials
│
│  ┌─ Customer org console  (/org/<slug>)     ─ onboarded org admins
│  │    sees:   their org's people, plan, usage, SSO config, projects list, billing
│  │    cannot: see other orgs, platform settings, other orgs' audit
│  │
│  │  ┌─ Project workspace  (/p/<id>/...)     ─ project members
│  │  │    sees:   this project only, per the member role (viewer/editor/owner)
```

The platform operator never sees customer spec contents (an existing invariant from the audit
log doc — `platform_audit_log` already excludes bodies and secrets). Org admins never see other
orgs. Project members never see projects outside their membership. This is the posture SOC 2
auditors expect to see documented, with proof of enforcement at every layer
([complydog.com][sc1], [securityscientist][sc2]).

---

## 2. Core concepts and relationships

### 2.1 Entities

- **Organization (new).** Every customer is an Organization — including a single-user "individual"
  account, which is just an Organization with one member and no SSO. One account type keeps the
  code paths uniform; the UI hides concepts (invites, SSO) that don't apply to a solo org.
- **PlatformUser (exists).** Unchanged shape; sign-in is still per user. A user can belong to many
  organizations (B2B pattern described by WorkOS, Clerk and Phase Two's Keycloak extension —
  "user can be in many organizations" since Keycloak 26 [ptw1][ptw2]). Each `(user, organization)`
  pair gets an `OrganizationMembership` with a role.
- **OrganizationMembership (new).** `(organization_id, user_id)` → role (`owner | admin | member`).
  Owners can transfer ownership, admins can manage people/plan, members just use.
- **Invitation (new).** Pending seat; email, role, token, expiry. Sent by an admin.
- **Project (exists).** Gets a new column `organization_id` so every project belongs to exactly
  one org. The existing `project_members` becomes a *subset* of that organization — adding someone
  to a project requires them to be a member of the project's org first.
- **Plan (new).** A row describing the limits: `max_seats`, `max_projects`, `max_api_tokens`,
  `allow_sso`, `allow_scim`, `allow_mcp`, custom overrides. Plans are seeded (`free`, `team`,
  `business`, `enterprise`) and are platform-defined.
- **Subscription (new).** `organization_id → plan_id`, plus `status` and the Stripe
  `customer_id` / `subscription_id` when billing is enabled. One active row per org.
- **SsoConnection (new, enterprise).** `organization_id → (protocol, idp metadata, verified_domains)`;
  one per org. Routing is by verified email domain, as recommended by SSOJet and Clerk
  ([ssojet][ssj], [clerk-sso][cs2]).
- **ScimDirectory (new, enterprise).** `organization_id → (bearer_token_hash, idp_type)`;
  independent of SsoConnection, as Clerk notes — JIT can't offboard; SCIM is the deactivation
  path ([clerk-scim][cs1], [descope-scim][dsc]).

### 2.2 Role hierarchy

Four layers, each read on every request and never trusted from a token claim alone (the existing
pattern in `app/core/platform_authz.py`):

| Scope        | Role              | Can…                                                                   |
|--------------|-------------------|------------------------------------------------------------------------|
| Platform     | `platform_admin`  | everything in `/admin`                                                 |
| Platform     | `platform_support`| read-only in `/admin`                                                  |
| Organization | `org_owner`       | all org-admin actions + transfer ownership + delete org                |
| Organization | `org_admin`       | invite/remove people, change seats within plan, configure SSO/SCIM, projects |
| Organization | `org_member`      | ordinary customer; project-level roles decide what they can touch       |
| Project      | `owner`           | existing: project IAM + MCP toggle (WP6)                                |
| Project      | `editor`          | existing                                                                |
| Project      | `viewer`          | existing                                                                |

Platform admin role is a totally separate audience (`TokenAudience.admin`), as it is today.
Org-admin and project roles are the same session; the API resolves scope per request. An org
member can't act in a different org even if they're an admin of theirs.

### 2.3 The "individual" degenerate case

A solo account is just an Organization with `kind = 'personal'`, one member who is both owner
and admin, SSO/SCIM switched off, projects limited by the free plan. If they later want
teammates, the UI exposes the admin surface and offers a plan upgrade. No forked code paths.

---

## 3. Data model (additive migrations)

Shared schema with a `tenant_id` column (`organization_id`) is the overwhelming consensus for
most B2B SaaS and the right default here — one migration path, PgBouncer-friendly, and when
combined with Postgres RLS it keeps a safety net even if application code forgets a filter
([clickhouse.com][iso1], [dev.to][iso2]). It's also what the project already does implicitly:
`project_members` is an application-level filter today.

### 3.1 New tables

```sql
CREATE TABLE organizations (
  id              uuid PRIMARY KEY,
  name            varchar(100) NOT NULL,
  slug            varchar(100) NOT NULL UNIQUE,  -- used in /org/<slug>
  kind            varchar(20)  NOT NULL,         -- 'personal' | 'team'
  created_by      uuid REFERENCES platform_users(id),
  created_at      timestamptz  NOT NULL DEFAULT now(),
  deleted_at      timestamptz
);

CREATE TABLE organization_members (
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  user_id         uuid NOT NULL REFERENCES platform_users(id) ON DELETE CASCADE,
  role            varchar(20) NOT NULL,  -- 'owner' | 'admin' | 'member'
  joined_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (organization_id, user_id)
);
CREATE INDEX ix_org_members_user ON organization_members(user_id);

CREATE TABLE organization_invitations (
  id              uuid PRIMARY KEY,
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  email           varchar(254) NOT NULL,
  role            varchar(20)  NOT NULL,
  token_hash      varchar(64)  NOT NULL UNIQUE,  -- hashed, same pattern as API tokens
  invited_by      uuid REFERENCES platform_users(id),
  expires_at      timestamptz NOT NULL,
  accepted_at     timestamptz,
  revoked_at      timestamptz
);

CREATE TABLE plans (
  id                 varchar(40) PRIMARY KEY,     -- 'free' | 'team' | 'business' | 'enterprise'
  display_name       varchar(100) NOT NULL,
  max_seats          int,                         -- NULL = unlimited; we never ship NULL for free/team
  max_projects       int,
  max_api_tokens     int,
  max_mcp_tokens     int,
  allow_sso          boolean NOT NULL DEFAULT false,
  allow_scim         boolean NOT NULL DEFAULT false,
  allow_mcp          boolean NOT NULL DEFAULT false,
  monthly_price_usd  int                          -- cents; 0 for free
);

CREATE TABLE subscriptions (
  organization_id    uuid PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
  plan_id            varchar(40) NOT NULL REFERENCES plans(id),
  status             varchar(20) NOT NULL,        -- 'active' | 'past_due' | 'canceled' | 'trial'
  trial_ends_at      timestamptz,
  current_period_end timestamptz,
  stripe_customer_id varchar(64),
  stripe_subscription_id varchar(64),
  seat_override      int,                         -- platform-granted bump above plan default
  updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sso_connections (
  id                  uuid PRIMARY KEY,
  organization_id     uuid NOT NULL UNIQUE REFERENCES organizations(id) ON DELETE CASCADE,
  protocol            varchar(10) NOT NULL,       -- 'saml' | 'oidc'
  idp_entity_id       varchar(500),
  idp_sso_url         varchar(500),
  idp_cert_pem        text,
  oidc_discovery_url  varchar(500),
  oidc_client_id      varchar(255),
  oidc_client_secret_enc bytea,                   -- envelope-encrypted (same crypto as auth_secrets)
  active              boolean NOT NULL DEFAULT false,
  created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sso_domains (
  domain          varchar(253) PRIMARY KEY,       -- 'acme.com', verified via DNS TXT
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  verified_at     timestamptz,
  dns_token       varchar(64) NOT NULL            -- shown in UI, verified in DNS
);
CREATE INDEX ix_sso_domains_org ON sso_domains(organization_id);

CREATE TABLE scim_directories (
  organization_id uuid PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
  bearer_hash     varchar(64) NOT NULL UNIQUE,
  active          boolean NOT NULL DEFAULT false,
  created_at      timestamptz NOT NULL DEFAULT now(),
  last_sync_at    timestamptz
);
```

### 3.2 Edits to existing tables

- `projects.organization_id uuid NOT NULL REFERENCES organizations(id)` — the fundamental change.
  Every project now belongs to an organization; it's the authoritative scope for every API call
  on `/projects/{id}/...`.
- `project_members` — unchanged in shape, but the service enforces "user must be a member of
  `projects.organization_id` before they can be added to this project."
- `platform_audit_log.organization_id uuid` — new nullable column; every org-scoped action
  stamps it so an org admin can read **only their own org's events** without leaking into others.
- `platform_users.default_organization_id uuid REFERENCES organizations(id)` — where the UI drops
  someone when they sign in and belong to several orgs.

### 3.3 Row-level security (phased)

Phase 1 enforces at the application layer, mirroring the existing project guard
(`app/services/access_service.py`). Phase 2 adds Postgres RLS as a defense-in-depth layer on
every `*_id`-scoped table. The pattern:

```sql
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects FORCE  ROW LEVEL SECURITY;  -- also apply to the table owner
CREATE POLICY tenant_isolation ON projects
  USING (organization_id = current_setting('app.organization_id', true)::uuid);
```

Each request binds `SET LOCAL app.organization_id = '<uuid>'` on the connection before touching
the DB. "SET LOCAL" is the detail that makes this safe on a pooled connection
([viprasol][iso3]); plain `SET` leaks across checkouts. Owners and superusers also need `FORCE`
to be bound by the policy ([bytebase-rls][rls1]). We never grant `BYPASSRLS` to the app role —
only to migration scripts.

Phase 1 ships without RLS; Phase 2 adds it under a feature flag and we test it under load before
flipping it on in production.

---

## 4. Authentication & SSO

### 4.1 Keep built-in auth for most customers

The existing built-in auth (`platform_auth_service.py`) handles sign-up, login, refresh rotation,
lockout, admin audience separation. Keep it. Every org starts there.

### 4.2 Enterprise SSO per organization

Enterprise customers point us at their IdP. For each org we store **one** SSO connection
(`sso_connections`) and one or more verified domains (`sso_domains`). The login flow becomes:

1. User types email → `/account/login/discover` → if the email domain matches a verified
   `sso_domains` row and the org has `active=true`, redirect to the IdP; otherwise fall through
   to the password form. This is tenant-first discovery, as SSOJet and Clerk recommend
   ([ssojet][ssj]).
2. On IdP callback, validate the assertion (signature, audience, time window, `InResponseTo` for
   SAML — the step SSOJet flags as security-critical).
3. If the authenticated email matches an existing `platform_users` row linked to this org, mint
   a session. Otherwise JIT-provision: create the user, add them to the org as `org_member`,
   stamp an audit event. JIT **only** on login; deactivation happens via SCIM.
4. Session is a normal customer-audience JWT, same as a password login. SSO is just a different
   way to obtain it.

Protocol per-org is stored because SAML is still the enterprise default while Google Workspace
and newer IdPs favor OIDC ([ssojet][ssj]). Both branches end at the same `platform_users` row.

**Keycloak reuse — considered and deferred.** The project already has a Keycloak integration,
but it exists to secure *generated* projects, not Builder itself. Making Builder a Keycloak
client is a plausible path (Keycloak Organizations in 26 supports per-org IdP federation and
multi-org users — [skycloak][kc1], [phasetwo][kc2]), but it's a big foundational change and
Keycloak's own SCIM support is third-party and marked experimental ([phasetwo-scim][kc3]). We
build native SSO/SCIM first; migration to Keycloak-as-Builder-IdP is an open option, not a
dependency.

### 4.3 SCIM 2.0 for provisioning (enterprise)

One bearer token per `scim_directories` row, generated in the org admin UI, shown once (same
pattern as PATs). The IdP calls:

- `POST /scim/v2/Users` → create a `platform_users` row and `organization_members` row.
- `PATCH /scim/v2/Users/{id} { "active": false }` → clear sessions, set
  `organization_members.role = NULL`-equivalent (remove the row), and bump the user's
  `token_version` to kill PATs.
- `POST /scim/v2/Groups` → ignored or mapped to roles via a configured dictionary
  (`"Owners" → org_owner`), as Descope recommends ([descope-scim][dsc]).

A SCIM-deactivated user who still has other personal orgs keeps those; only this org's
membership and this org's tokens die. This is also where "right to be forgotten" (GDPR Art. 17)
sits.

### 4.4 MFA

Phase 1: optional TOTP for every user (built-in). Phase 2: WebAuthn/passkeys. Platform-admin
accounts require MFA at all times. Org admins can require MFA for all members of their org via a
per-org policy flag.

### 4.5 Impersonation

Platform operators sometimes need to see what a customer sees to debug. We will not reuse the
customer's session. Instead:

- Operator presses "View as this user" in `/admin`.
- Server mints a short-lived (10 min) *scoped* access token with the real user's sub plus an
  `impersonator_sub` claim.
- Every request made with it is logged in the audit trail with `via = "impersonation"` and the
  impersonator's ID. The dashboard shows a persistent "You are viewing as X" banner.
- Writes are blocked for impersonation sessions unless the operator explicitly flips a
  short-lived "allow writes" toggle (also audited).

This is a privileged action; it needs its own `impersonate` ADMIN permission, platform-admin
only, and daily digest to a security channel.

---

## 5. Authorization: how a request is resolved

Expansion of the existing request guard:

```
request → extract bearer → principal (user, scopes, audience)
       → route template → required_platform_role? required_org_role? required_project_role?
       → resolve the owning organization and (if applicable) project
       → check platform/org/project membership and roles
       → check scopes (unchanged: read/write/generate/mcp:*)
       → set LOCAL app.organization_id and app.user_id on the DB connection
       → run handler
```

Each layer is a flat table of (method, template) → required role, as it is now in
`platform_authz.py`. The addition is `required_org_role` and the mapping from route to
organization (via `projects.organization_id` for project routes, direct `/orgs/{slug}` for
org routes).

Default-deny: an unlisted template is refused. A test walks the OpenAPI schema to catch new
unlisted routes at CI time (same pattern as the existing `project_of()` guard test).

---

## 6. Plans, seats, quotas, entitlements

### 6.1 Reality of what Stripe gives you

Stripe Entitlements are **boolean** feature flags, not counters, and they are not real-time
enforced ([makerkit-ent][mk1], [dev-ent][de1]). You get a webhook when a subscription changes.
That means: **the platform is authoritative on usage; Stripe is authoritative on money**.
Vendors like Schematic, Stigg, Lago exist in the "run time entitlement enforcement" gap
([schematic][sch]).

We enforce in-app, cache in a `subscriptions` row, and reconcile with Stripe via webhook. Same
model Cal.com uses: count members from the DB, send Stripe the quantity, let Stripe prorate
([cal-seat][cal1]).

### 6.2 Enforcement points

The quota lives on `plans + subscriptions.seat_override`. Enforcement is at every write that
could grow a counter, in a transactional block that locks the subscription row to prevent races:

```python
async def enforce_seat(session, organization_id) -> None:
    sub = await session.execute(
        select(Subscription).where(Subscription.organization_id == organization_id).with_for_update()
    )
    plan = await session.get(Plan, sub.plan_id)
    cap = sub.seat_override or plan.max_seats
    if cap is None: return  # unlimited
    members = await _count_members(session, organization_id)   # excludes pending invites
    pending = await _count_pending_invites(session, organization_id)
    if members + pending >= cap:
        raise AppError("seat_limit", 402, f"Plan '{plan.id}' allows {cap} seats.")
```

The service calls this inside the transaction that creates the invite or accepts it; the
`SELECT ... FOR UPDATE` serializes concurrent attempts so a double-click can't exceed the cap.

Resources we gate (phase 1):

| Resource     | Counter                                   | Enforced at                           |
|--------------|-------------------------------------------|---------------------------------------|
| Seats        | active members + pending invites          | invite create, invite accept, SCIM create |
| Projects     | `projects WHERE organization_id = X`      | `POST /projects`                      |
| API tokens   | active tokens per user per org            | `POST /account/tokens`                |
| MCP tokens   | tokens with any `mcp:*` scope per org     | `POST /account/tokens` when scope ∈ mcp |
| SSO on/off   | `plans.allow_sso`                         | SSO connection create / activate       |
| SCIM on/off  | `plans.allow_scim`                        | SCIM directory create                 |

Each check returns a `402 Payment Required` with the plan name and the current cap, so the UI
can hyperlink to the plan page. Never silently drop; auditors look for the deny log entry
([complydog][sc1]).

### 6.3 Billing sync

Stripe webhook events (`checkout.session.completed`, `customer.subscription.updated`,
`invoice.payment_failed`) update the `subscriptions` row. The platform's own view of the plan
only moves on an event, never on a UI click. Downgrading past the current member count is
allowed but produces a warning in the UI and an audit event; new invites refuse until the count
is back within the new cap. This is the "soft-fail current users, hard-fail new ones" approach
most SaaS take.

### 6.4 Seat accounting mode

We ship **high-water-mark** by default (bill for the peak seat count during the cycle), which is
the Cal.com default and the most common ([cal-seat][cal1]). "Active user only" is an open option
for a later plan tier if the market asks.

### 6.5 "Platform operator override"

In your `/admin` console you can set `subscriptions.seat_override = N` to grant a specific org
more seats than their plan allows, with a reason. This is audited. Needed for sales/support
flexibility.

---

## 7. The operator console: `/admin` (extensions)

Already exists; grows new tabs and controls, all platform-admin only:

- **Organizations tab (new).** List every org, with plan, member count, project count, MRR,
  status, last activity. Click into an org → see members (read-only), projects (metadata only),
  SSO/SCIM status, Stripe link, audit tail scoped to this org. **Never** see the project's spec
  or decrypted credentials — that invariant stays.
- **Plans tab (new).** CRUD the `plans` catalog. Change caps; existing subscribers are grandfathered
  until they change plans, and the change is audited.
- **Billing tab (new).** List subscriptions, overdue invoices, trial expirations. Deep-link to the
  Stripe Dashboard rather than copying its UI.
- **Audit (exists; extend).** New filter: `organization_id`. New event prefixes: `org.*`,
  `sso.*`, `scim.*`, `plan.*`, `impersonation.*`.
- **Impersonation (new).** Button on an org member row. Guarded as above.
- **Insights (new).** Lightweight dashboard: signups/day, orgs/day, active orgs (any
  write-event last 7 days), total projects, total MCP calls last 24 h, denied-by-quota count.
  Everything here is already in `platform_audit_log`; this is reporting, not new instrumentation.
  No per-user behavioral tracking beyond what the audit log already keeps — that line matters
  for SOC 2 ("minimum necessary data") and GDPR.

### 7.1 What operators cannot see

Explicit, written-in-the-UI rules so your customers can quote them in their security
questionnaires:

- No access to project specs, auth secrets, SMTP/SMS credentials, payment keys, storage keys,
  Keycloak configs, generated code, or audit `detail` fields that contain customer data.
- No ability to decrypt a secret column — the admin role doesn't carry the key.
- Impersonation requires explicit consent via a per-org policy toggle (default: on, so your
  support team can help; an enterprise org can turn it off and operators then can't impersonate).

---

## 8. The customer org console: `/org/<slug>` (new)

A new top-level route in the customer-audience app, accessible to any member of the org. What
each role sees:

### Members (`org_member`)
- Their own profile and tokens.
- The org's projects list (filtered to projects they're a member of).
- A link to the org's name and plan status (no billing details).

### Admins (`org_admin`)
- **People.** Table of members with role, email, status, 2FA on/off, last sign-in. Buttons:
  Invite, Change role (except Owner), Remove.
- **Invites.** Pending invites with the time left, resend, revoke.
- **Projects.** All projects of the org (metadata). Can add themselves to any one; can transfer a
  project between orgs they own.
- **Plan.** Current plan, usage ("3 of 5 seats, 2 of 10 projects"), upgrade/downgrade.
- **SSO & SCIM (if `plans.allow_sso`).** DNS domain verification UI, SAML/OIDC config form, test
  button, SCIM token generation.
- **Security policies.** Require MFA for all members, allow/deny platform-operator impersonation,
  default session TTL.
- **Audit log.** Org-scoped slice of `platform_audit_log`, same filters as `/admin` but filtered
  server-side to this org only — queries receive an unconditional `organization_id = X` filter.

### Owners (`org_owner`)
- Everything above, plus: transfer ownership, delete organization.

### Non-admins get a clear "ask your admin" message
Hitting any admin-only panel returns a 403 with the owner's email, so the user knows who to
ping — a small UX detail, but it kills a support ticket.

### 8.1 Routing in the UI
- `#/org/<slug>` → people
- `#/org/<slug>/plan` → plan + usage
- `#/org/<slug>/sso` → SSO & SCIM
- `#/org/<slug>/policies` → security policies
- `#/org/<slug>/audit` → audit log

Each project page already shows an org breadcrumb; we add the inverse (org page → projects list)
to make navigation symmetric.

---

## 9. Multi-tenant data isolation

Review of our choices against the SOC 2 / isolation checklist:

- **Shared schema + `organization_id` on every scoped table.** Standard default
  ([clickhouse][iso1]).
- **Tenant filter in SQL and re-checked in Python at every layer** (same model the generated
  projects already use for `tenant` row rule).
- **Phase 2 Postgres RLS** with `FORCE ROW LEVEL SECURITY` for defense in depth
  ([bytebase-rls][rls1]).
- **Tenant-aware logs.** Every log line and every audit row has an `organization_id` tag. The
  operator UI's "view as org" filters strictly by that.
- **Encrypted secrets** are per-org and envelope-encrypted with a KEK that `/admin` role doesn't
  carry — the invariant inherited from `auth_secrets.py`.
- **Backups.** `pg_dump` is cluster-wide, but customer data export is per-org (one future
  endpoint: `GET /org/<slug>/export`), which is a Processing Integrity criterion
  ([complydog][sc1]).
- **Pen testing** of cross-tenant leakage before launch — a mandatory item on the SOC 2 checklist
  cited above.

What we're not doing in phase 1 and why:
- **Separate database per tenant.** Fine for a bank, overkill for us; we lose the single-pool,
  single-migration operational simplicity that is the main benefit of shared schema.
- **Schema per tenant.** Known to degrade past a few thousand schemas ([dev.to][iso2]); we are
  planning for more than that.

---

## 10. Billing integration

Stripe. One Stripe Customer per Organization. One Stripe Subscription per Organization. Line
items (per plan):

- Flat per-plan fee (if any).
- Seat line item billed at the plan's per-seat price × high-water-mark seat count.
- Metered line item for anything we charge usage on later (MCP calls above a cap, generated
  zips, etc.) — optional; starts off.

Flow (phase 2, after the free/team plans ship):

- Org admin clicks "Upgrade" → Stripe Checkout, prefilled with the org's Stripe Customer and
  the target plan's Price. (Checkout handles card entry; cards never touch the Builder.)
- On `checkout.session.completed` the webhook stamps `subscriptions.plan_id` and `status`.
- On a membership change inside the app, if the subscription is active, we PATCH the subscription
  item's quantity to the new seat count; Stripe prorates.
- On `invoice.payment_failed` the subscription goes `past_due`; the admin UI shows a banner and
  blocks new seats and new projects but lets existing operations continue (same soft-fail model
  as the plan downgrade case).

No card data in logs, no card data in audit; audit records the Stripe event id only (same
pattern already in `app/core/generator/features/payments/`).

---

## 11. Compliance & audit posture

What a SOC 2 auditor will ask for and how we answer, cross-referenced to the plan:

| Control                                              | Where it lives                                        |
|------------------------------------------------------|-------------------------------------------------------|
| CC6: logical access, incl. tenant isolation          | §9 (shared schema + RLS), §5 (per-request guard)      |
| CC7: system monitoring, anomaly detection            | §7 insights (denied-by-quota, failed logins), existing `platform_audit_log` trigger that refuses UPDATE/DELETE |
| Availability: durability, backup, DR                 | Standard Postgres backup + per-org export             |
| Confidentiality: encryption of secrets, keys         | Existing `auth_secrets` envelope encryption + §4.3 SCIM secret handling |
| Processing Integrity: tenant-scoped exports          | §9 (per-org export), §8 admin audit                   |
| Privacy: minimal necessary data, right to erasure    | §7.1 (operators see no spec content), §4.3 (SCIM deactivation path), per-org GDPR delete  |

Documentation deliverables as part of this project:
- `docs/MULTITENANT_ARCHITECTURE.md` describing the isolation model (needed for the SOC 2
  system description).
- `docs/SSO_SETUP.md` for enterprise customers (public).
- `docs/SCIM_SETUP.md` for enterprise customers (public).
- Yearly cross-tenant pen test, scoped specifically against isolation controls.

---

## 12. Rollout plan (phased)

Order chosen so each phase ships value without blocking the next. Each phase has its own
migration, its own tests, its own UI entry — no half-landed states.

### Phase A — Organizations core (foundational)
1. Migration: `organizations`, `organization_members`, `organization_invitations`,
   `plans`, `subscriptions`; `projects.organization_id`, `platform_audit_log.organization_id`,
   `platform_users.default_organization_id`. Seed `free` and `team` plans.
2. Backfill: every existing `platform_users` gets a `kind='personal'` org, becomes its owner;
   their projects migrate under it. No user-visible break.
3. Service layer: `OrganizationService` (CRUD, invite, accept, role change, remove, transfer).
   Guard rewrite to resolve `required_org_role`. Project service: new project requires
   `organization_id`.
4. Customer-facing API: `/orgs`, `/orgs/{slug}/members`, `/orgs/{slug}/invitations`,
   `/orgs/{slug}/plan` (read-only initially).
5. Operator admin: `Organizations` tab, `Plans` tab.
6. Frontend: `/#/org/<slug>` with People, Projects, Plan tabs. Project workspace shows the org.
7. Tests: integration tests of every quota check (invite accept race, concurrent token creates).

### Phase B — Plan enforcement and seat accounting
1. Transactional quota checks at every enforcement point in §6.2.
2. UI: per-plan usage cards, 402 handling with upgrade CTAs.
3. Seat-override field in operator console.
4. Stripe wired up in Checkout mode (no webhook yet); plan changes are initially manual by
   operators.

### Phase C — Stripe automation
1. Stripe Customer + Subscription per org.
2. Checkout session, success and cancel URLs.
3. Webhook handler with signature verification; sync `subscriptions` on
   `checkout.session.completed`, `customer.subscription.updated`, `invoice.payment_failed`.
4. Seat sync on membership change (via `subscription_item.quantity`).
5. Soft/hard fail behavior on `past_due`.

### Phase D — Enterprise SSO (SAML + OIDC per org)
1. Migration: `sso_connections`, `sso_domains`.
2. DNS TXT verification for the domain; verified-domain → org routing.
3. SAML + OIDC adapters; SP metadata endpoint `/sso/metadata/{org}`.
4. JIT provisioning, including "allowed roles for JIT" setting on the org.
5. Operator admin: SSO status column on orgs; test-connection button.
6. Customer admin: full SSO config form; "test with my own email" flow.
7. MFA policy per org.

### Phase E — SCIM 2.0 directory sync
1. Migration: `scim_directories`.
2. SCIM endpoints: Users (create/get/list/patch/delete), Groups (create/list/patch/delete),
   ServiceProviderConfig, ResourceTypes, Schemas. Bearer-token auth; tenant resolved from token.
3. Role mapping dictionary (SCIM group → org role).
4. Operator admin: SCIM status column, bearer-token rotation.
5. Customer admin: SCIM setup page with the bearer and the Users endpoint URL.
6. Compatibility checklist against the four big IdPs (Okta, Entra ID, JumpCloud, Google
   Workspace) — Clerk's own compatibility matrix is a good target ([clerk-scim][cs1]).

### Phase F — Hardening
1. Postgres RLS on every scoped table.
2. Cross-tenant pen test.
3. Impersonation flow with the banner, consent policy, and audit.
4. Per-org data-export endpoint.
5. SOC 2 Type I evidence collection.

Each phase is a self-contained landable chunk. We can pause between any two phases and the
platform still works.

---

## 13. Open questions and deliberate "not-nows"

- **AI/MCP quota per plan.** We gate MCP on/off per plan today; a "MCP calls per month" cap is
  easy to add once we see what customers actually do.
- **Multiple orgs per project.** Hard no — a project belongs to exactly one org. Collaboration
  across orgs would be a feature named "sharing" built on top, not a tenancy change.
- **Reseller / white-label.** Out of scope. Would be a separate product tier that owns a slice of
  the orgs catalog — a layer above Organization. Doable, not now.
- **Native payments across orgs** (one org pays for another). Out of scope.
- **Keycloak-as-Builder-IdP.** Reconsider after Phase E ships if we see enterprise customers
  wanting the full Keycloak feature set for Builder itself. The migration is doable because every
  org has a stable UUID that maps 1:1 to a Keycloak Organization.
- **Row-level security.** Phase 1 enforces at the service layer; RLS is Phase F. We go without
  it to start because the generator's existing isolation pattern (which we're mirroring) does the
  same, and we can add RLS without a schema change later.
- **Impersonation default.** We default it to **on, requiring consent-in-UI**, which is a bit
  more permissive than enterprise expectations. Open to flipping it before launch.
- **Audit `detail` content.** Already excludes bodies and secrets; we need to add
  `organization_id` to every event. One migration + one `audit_service.record` edit.

---

## 14. Why this shape (short rationale)

- **One account model (orgs always, "individual" = org-of-one).** Removes the code fork that
  usually gets you between two-sided SaaS and single-user SaaS. Clerk's Multi-Tenancy for B2B
  guide and WorkOS's docs both describe the org-first model
  ([clerk-mt][cm1]).
- **Shared schema, app-level isolation first, RLS later.** Operational simplicity + a safety net
  path; this is the mainstream pattern ([clickhouse][iso1], [dev.to][iso2]).
- **Platform is authoritative on usage; Stripe is authoritative on money.** Stripe's own
  Entitlements are boolean and not real-time ([makerkit-ent][mk1], [dev-ent][de1]); we can't rely
  on them for seat caps. Our DB counts; the webhook keeps money in sync.
- **Keep built-in auth; add SSO per-org.** Smaller orgs don't want SSO; big ones won't onboard
  without it. Separating "has an IdP connection" from "is a customer" matches SSOJet's and
  Clerk's enterprise onboarding pattern.
- **Separate SCIM from SSO.** They're independent per Descope and Clerk; our schema reflects
  that ([descope-scim][dsc], [clerk-scim][cs1]).
- **Operators cannot read customer specs.** This is the invariant that sells enterprise. Everything
  in §7.1 flows from it.

---

## Sources

- [Clerk: Multi-tenancy for B2B](https://clerk.com/multi-tenancy) [cm1]
- [WorkOS vs. Auth0 vs. Clerk 2026](https://workos.com/blog/workos-vs-auth0-vs-clerk-the-best-auth-platform-for-b2b-saas-in-2026)
- [Scalekit on Clerk B2B fit](https://www.scalekit.com/blog/is-clerk-the-right-fit-for-b2b-ai-apps)
- [How to architect multi-tenant SaaS on Postgres (ClickHouse)](https://clickhouse.com/resources/engineering/multi-tenant-saas-postgres-architecture) [iso1]
- [Multi-tenant Postgres RLS vs schema-per-tenant (DEV.to)](https://dev.to/itsjayanth/multi-tenant-postgresql-row-level-security-vs-schema-per-tenant-when-to-use-which-3joe) [iso2]
- [Choosing PostgreSQL Schema Patterns (Viprasol)](https://viprasol.com/blog/postgresql-multi-tenant-saas-schema-india/) [iso3]
- [Postgres RLS reference (Bytebase)](https://bytebase.com/reference/postgres/how-to/postgres-row-level-security) [rls1]
- [Enterprise SSO for Multi-Tenant SaaS (SSOJet)](https://ssojet.com/blog/add-enterprise-sso-multi-tenant-saas) [ssj]
- [SCIM 2.0 practical guide (Clerk)](https://clerk.com/articles/scim-2-0-explained-a-practical-guide-for-saas-auth) [cs1]
- [Federated identity: SAML/OIDC/SCIM (Clerk)](https://clerk.com/articles/federated-identity-for-enterprise-saas-saml-oidc-and-scim-2) [cs2]
- [SCIM providers for B2B SaaS (Descope)](https://www.descope.com/blog/post/scim-providers-b2b-saas) [dsc]
- [SOC 2 Trust Principles (Mintlify)](https://www.mintlify.com/Basit-Ali0/Yggdrasil/frameworks/soc2)
- [Multi-tenant isolation controls Q&A (Security Scientist)](https://www.securityscientist.net/blog/12-questions-and-answers-about-multi-tenant-isolation-controls-for-compliance/) [sc2]
- [Complydog: Multi-tenant SaaS Privacy & Compliance](https://complydog.com/blog/multi-tenant-saas-privacy-data-isolation-compliance-architecture) [sc1]
- [Stripe seat sync (WorkOS)](https://workos.com/blog/stripe-seat-sync-workos)
- [Per-seat billing (MakerKit)](https://makerkit.dev/docs/md/tanstack-supabase/billing/per-seat-billing)
- [Plan Limits & Entitlements (MakerKit)](https://makerkit.dev/docs/md/nextjs-drizzle/billing/entitlements) [mk1]
- [Stripe Entitlements critique (DEV.to)](https://dev.to/andrewp629/stripe-entitlements-break-the-moment-you-need-real-usage-control-5e0f) [de1]
- [Entitlement management overview (Schematic)](https://schematichq.com/blog/entitlement-management-software) [sch]
- [Cal.com seat billing](https://cal.com/help/billing-and-usage/seat-billing) [cal1]
- [Keycloak Organizations guide (Skycloak)](https://skycloak.io/blog/multitenancy-in-keycloak-using-the-organizations-feature/) [kc1]
- [Phase Two orgs extension (Keycloak)](https://medium.com/@phasetwo/phase-twos-organizations-a-keycloak-multi-tenant-extension-and-keycloak-s-upcoming-organization-s-42f86663f8ee) [kc2]
- [Phase Two SCIM extension](https://phasetwo.io/blog/orgs-scim-experimental/) [kc3]
- [Keycloak Organizations vs Realms](https://medium.com/@vgzxkgmrpn/keycloak-organizations-vs-realms-two-tools-two-completely-different-jobs-a022f8e1592e) [ptw1]
- [Phase Two Keycloak Organizations](https://medium.com/@phasetwo/phase-twos-organizations-a-keycloak-multi-tenant-extension-and-keycloak-s-upcoming-organization-s-42f86663f8ee) [ptw2]