# WP6 — MCP Server: Extended Research, Design & Findings

Written 2026-10-26. Covers:
1. The concrete org-scoped scenario you described
2. What the current code already handles
3. What is missing (gaps, bugs, blockers, improvements) — categorised
4. Full MCP + IAM design that satisfies all the cases
5. A complex worked example covering every depth of the model
6. Research notes (MCP spec, auth, tool security)

Companion files: `MASTER_PLAN.md` §WP6, `README.md`.

---

## 1. The scenario, fully expanded

You described two overlapping scenarios. I'll make them precise.

### Scenario A — individual API tokens, multi-user SaaS

Three independent users each have an account on the builder platform.

| User | Projects they own / are a member of | MCP scope granted |
|---|---|---|
| alice@acme.com | Blog, Shop, API-Docs, Analytics | all 4 |
| bob@acme.com | Dashboard, Notes, Webhook-Hub, Report-Gen | all 4 |
| carol@acme.com | Landing-Page, CMS, Admin-Portal | all 3 |

Each user creates an API token with `mcp:read` scope. When they connect that token to
Lovable / Claude / Cursor, `list_projects` **must return only the projects that token's user is
a member of** — never a peek at another user's projects.

### Scenario B — an org buys the platform; internal IAM is needed

One company ("Acme Corp") pays for the builder. They have 8 projects and 3 developers.

```
Acme Corp (org admin: priya@acme.com)
├── Project: customer-api      → dev1 (owner), dev2 (editor)
├── Project: billing-service   → dev1 (viewer), dev3 (owner)
├── Project: auth-service      → dev1 (editor), dev2 (editor), dev3 (viewer)
├── Project: analytics-api     → dev2 (owner)
├── Project: notification-svc  → dev3 (editor)
├── Project: file-service      → dev1 (owner), dev3 (viewer)
├── Project: payment-gateway   → dev2 (editor), dev3 (owner)
└── Project: admin-portal      → dev1 (owner)
```

dev1 has MCP access on: customer-api, auth-service, file-service, admin-portal (4 projects)
dev1 does NOT have MCP access on: billing-service (even though they're a viewer), analytics-api,
notification-svc, payment-gateway.

**Key insight from your description:** MCP access ≠ project membership. A developer can be a
project member but the org admin can independently decide whether they may use the MCP tool on
that project. This is a **per-(member, project) MCP grant**, separate from the member role.

dev2 has MCP access on: auth-service, analytics-api (2 projects, not payment-gateway)
dev3 has MCP access on: billing-service (1 project, not notification-svc which they edit)

The org admin (priya) needs to:
- See every token created by every dev under this org's projects
- Revoke any token
- See the full audit trail of MCP tool calls per project
- Grant or remove MCP access per developer per project

---

## 2. What the current code already gives us (strong foundations)

Reading the code carefully, WP1 delivered a very solid base:

### 2.1 API tokens with project pinning — ALREADY EXISTS

`ApiToken.project_id` (nullable FK to `projects`) exists in the model and service.
When set, the `guard` in `security.py` enforces:

```python
if principal.token_project_id is not None and principal.token_project_id != project_id:
    raise not_found()
```

And for `GET /projects` (list):
```python
if principal.token_project_id is not None and method != "GET":
    raise forbidden("this API token is limited to one project", ...)
```

So a token pinned to `customer-api` literally cannot see any other project. This already covers
the "pinned token" case.

### 2.2 MCP scopes — ALREADY RESERVED

`platform_authz.py` already defines:
```python
SCOPE_MCP_READ  = "mcp:read"
SCOPE_MCP_WRITE = "mcp:write"
VALID_SCOPES    = frozenset({SCOPE_READ, SCOPE_WRITE, SCOPE_GENERATE, SCOPE_MCP_READ, SCOPE_MCP_WRITE})
```

Comment says: *"Reserved for the MCP endpoint (WP6) so tokens minted now keep working then."*
Excellent foresight. Tokens already being created with `mcp:read` will work.

### 2.3 Project membership scoping — ALREADY EXISTS

`access_service.member_role()` is called on every request. A user who is not a member of a
project gets `404` (not `403` — correct, prevents enumeration). The `list_projects` endpoint
naturally returns only projects the caller is a member of (the service filters by membership).

### 2.4 Audit log — ALREADY EXISTS

Every project change, every access denial, every token operation goes into `platform_audit_log`
with `actor_id`, `actor_email`, `via` (distinguishes `api_token` from `session`), `project_id`,
`client_ip`, `request_id`, `detail`. The append-only trigger prevents tampering.

### 2.5 Token list is per-user — ALREADY EXISTS

`ApiTokenService.list()` filters `ApiToken.user_id == user.id`. A user only sees their own tokens.

---

## 3. Gaps, bugs, blockers and improvements

Categorised into four tiers. Each item has an ID for tracking.

---

### TIER 1 — BLOCKERS (WP6 cannot ship without these)

#### B1 — `mcp:generate` scope is missing from VALID_SCOPES

**File:** `app/core/platform_authz.py`

**Current state:**
```python
SCOPE_MCP_READ  = "mcp:read"
SCOPE_MCP_WRITE = "mcp:write"
VALID_SCOPES    = frozenset({SCOPE_READ, SCOPE_WRITE, SCOPE_GENERATE,
                             SCOPE_MCP_READ, SCOPE_MCP_WRITE})
```

`SCOPE_MCP_GENERATE` is referenced in `MASTER_PLAN.md §WP6` design:
> `generate_project` returns a download link (scope `mcp:generate`), never inline secrets.

But it does not exist in the code. Any token created with `mcp:generate` would be rejected with
`invalid_scope`. The MCP `generate_project` tool cannot exist until this is added.

**Fix required:**
```python
SCOPE_MCP_GENERATE = "mcp:generate"
VALID_SCOPES = frozenset({
    SCOPE_READ, SCOPE_WRITE, SCOPE_GENERATE,
    SCOPE_MCP_READ, SCOPE_MCP_WRITE, SCOPE_MCP_GENERATE,
})
```

---

#### B2 — No per-project MCP access grant (the "org admin controls MCP per developer per project" requirement)

**Current state:** MCP access is purely determined by whether the token has `mcp:read` / `mcp:write` scope and whether the user is a project member. There is no way for an org admin to say "dev1 is a member of billing-service but may NOT use MCP on it."

**The gap:** The scenario requires a `mcp_enabled` flag on `ProjectMember`, or a separate
`project_mcp_grants` table, that the org admin (project owner) controls. Without this, granting
someone project membership automatically grants them MCP access if they have a scoped token,
which contradicts the requirement.

**Proposed design:** Add `mcp_enabled: bool = False` to `ProjectMember`. Default `False` (deny
by default, consistent with the project's philosophy). A project owner flips it per member.
The MCP guard checks this flag before any tool call.

This requires:
- A migration: `ALTER TABLE project_members ADD COLUMN mcp_enabled BOOLEAN NOT NULL DEFAULT FALSE`
- Updated `MemberService.add()` to accept `mcp_enabled`
- New endpoint `PATCH /projects/{id}/members/{user_id}/mcp` or include in the existing `PATCH`
- MCP guard: after membership check, also verify `mcp_enabled` on the member row

**Impact:** Medium-sized. One migration, one model change, one service change, guard change.

---

#### B3 — No `GET /admin/users/{user_id}/tokens` — org admin cannot see dev tokens

**Current state:** `ApiTokenService.list()` only lets a user see their own tokens. There is no
admin endpoint to list tokens for another user. An org admin (project owner) cannot audit which
tokens their developers have minted, cannot revoke them, cannot see when they were last used.

**From your requirement:**
> "orgs admin should able to see and orgs admin should able to log that properly and do various
> operations of the user"

**What's missing:**
1. `GET /admin/users/{user_id}/tokens` — list tokens for any user (admin only)
2. `DELETE /admin/users/{user_id}/tokens/{token_id}` — revoke a specific token (admin only)
3. Token revocation is already audited in `ApiTokenService.revoke()`, but there is no admin path

**Note:** "Org admin" in the current model is a `platform_admin` or `platform_support` role —
there is no organisation-scoped admin concept (see G1 below). This means today, only the
platform-level administrator can do this. The per-org admin use case needs new work.

---

#### B4 — `list_projects` pinned-token filtering ✅ ALREADY CORRECT (not a bug)

**Verified by reading `app/api/projects.py` and `app/services/project_service.py`.**

The `GET /projects` endpoint already passes `principal.token_project_id` to the service:
```python
projects, total = await ProjectService(session).list(
    principal.user.id, page.limit, page.offset, principal.token_project_id  # ← passed
)
```

And `ProjectService.list()` correctly applies it:
```python
async def list(self, user_id, limit, offset, only_project=None):
    member_of = select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)
    conditions = [Project.id.in_(member_of)]
    if only_project is not None:
        conditions.append(Project.id == only_project)  # ← filters to pinned project
```

**This is NOT a bug.** A pinned token already returns only the pinned project. B4 is resolved.
Remove from the blocker list — update G4 accordingly.

---

#### B5 — No MCP endpoint exists yet

**Current state:** `/mcp` does not exist. WP6 is marked `[ ]` (not started).

This is expected — it's the whole point of WP6. But it is listed here because the `mcp` package
(`D4` decision in MASTER_PLAN) is not in `pyproject.toml` yet. Need to add and pin it before
building.

---

### TIER 2 — GAPS (important for the org scenario you described, required before selling to orgs)

#### G1 — No "organisation" concept; platform roles are flat

**Current state:** Every user is one of: `customer`, `platform_support`, `platform_admin`.
Project roles are: `viewer`, `editor`, `owner` — scoped to one project.

**The gap:** When you sell to an org, the org has an internal admin ("priya@acme.com") who manages
their own team's access. Right now, "admin" means platform-admin (your staff). There is no
`org_admin` role that gives a customer elevated control over only their own org's projects.

**What an org admin needs that a regular project owner does not:**
- See all tokens created by any user on any of the org's projects (B3)
- See audit logs filtered to only their org's activity
- Invite/create users into their own org (not open to the public)
- Set org-wide MCP policy ("only these 2 developers in this org may use MCP at all")

**Design options:**
1. **Simple:** A project `owner` already has most of this power per project. Extend `owner` to
   include the ability to see member tokens and audit logs for their projects. This is the minimal
   path and fits the current architecture.
2. **Full org model:** Add an `organisations` table, make projects belong to an org, add an
   `org_admin` role. This is a larger change (new migration, new service, IA changes).

**Recommendation:** Option 1 for WP6. Option 2 as a follow-up work package (WP10). Document the
limitation clearly.

---

#### G2 — Token list for admins does not include MCP-specific metadata

**Current state:** `ApiTokenRead` contains: `id`, `name`, `public_id`, `scopes`,
`project_id`, `created_at`, `expires_at`, `last_used_at`, `revoked_at`.

**Missing for MCP audit visibility:**
- No `via` or `last_used_via` — you cannot tell if the token was used by Lovable vs a curl script
- The audit log has `via` = `"api_token"` but does not record which MCP tool was called
- No `mcp_tool_calls_count` or last MCP call timestamp — just `last_used_at` which conflates all uses

**Required addition:** The MCP layer must emit its own specific audit events:
```
action: "mcp.tool_call"
detail: {"tool": "get_data_model", "project_id": "...", "result": "ok"}
```
This gives the org admin a proper MCP activity feed distinct from API usage.

---

#### G3 — `SCOPE_MCP_WRITE` is not wired into `required_scope()` in `platform_authz.py`

**File:** `app/core/platform_authz.py`

**Current state:** `required_scope()` only knows about `read`, `write`, `generate`:
```python
def required_scope(method: str, template: str) -> str:
    if "/generate/" in template or template.startswith("/generations/"):
        return SCOPE_GENERATE
    if (method.upper(), template) in _READ_ONLY_POSTS:
        return SCOPE_READ
    return SCOPE_READ if method.upper() in _READ_METHODS else SCOPE_WRITE
```

The MCP endpoint at `/mcp` will not be a REST endpoint — it is a WebSocket/SSE/HTTP streaming
endpoint (MCP streamable HTTP transport). The standard `required_scope()` function, which is
called by the `guard` dependency, will not understand MCP tool calls. The MCP layer needs its
**own authorization layer** that checks `mcp:read` / `mcp:write` / `mcp:generate` per tool call,
not per HTTP method/route.

**Design implication:** The MCP endpoint itself must be exempt from the standard `guard`
(it cannot have a project_id in the URL; tool calls carry project ids in their arguments). It
must implement its own principal resolution + MCP-scope check + per-tool project membership
check.

---

#### G4 — ✅ Already handled (see B4 above)

`ProjectService.list()` already accepts and applies `only_project`. No change needed.

---

#### G5 — No `GET /projects/{id}/members/{user_id}/tokens` (owner sees tokens of their members)

**The org scenario requires:** A project owner (who is acting as an org admin) can see which API
tokens their team members have that are scoped to this project, and can revoke them.

**Current gap:** There is no endpoint for this. The admin service lists all tokens for any user
(platform admin only), and member endpoints do not expose tokens.

**Proposed endpoint:**
```
GET  /projects/{id}/tokens          # list all active tokens scoped to this project (owner only)
DELETE /projects/{id}/tokens/{tid}  # revoke a member's token on this project (owner only)
```

This lets the project owner manage tokens without needing platform-admin access.

---

#### G6 — Audit log has no filter by `via = "api_token"` or by token `public_id`

**Current state:** `GET /admin/audit` supports filters: `actor_id`, `action`, `project_id`,
`since`, `result`. It does NOT support filtering by `via` or by the token's `public_id`.

**Required:** To give an org admin "show me everything this MCP token did on my project":
```
GET /admin/audit?via=api_token&project_id=xxx&action=mcp.tool_call
```

The `platform_audit_log` table has the `via` column but the search function does not expose it.
`audit_service.search()` needs a `via` parameter, and `GET /admin/audit` needs to pass it.

---

### TIER 3 — IMPROVEMENTS (valuable, non-blocking for the first MCP release)

#### I1 — Token creation endpoint does not validate that MCP scopes are only used with project-pinned tokens

**Rationale:** An `mcp:read` token without a `project_id` pin creates ambiguity: which project
should the MCP client see? The answer today is "all the user's projects" (which is valid for
`list_projects`), but it is also a wider blast radius than needed. Best practice: warn or reject
`mcp:*` tokens without a project pin if the requester is a `viewer` — they should not be building
things on projects they cannot change.

---

#### I2 — No MCP-specific rate limiting

**Current state:** Rate limiting exists for auth endpoints (sliding window in `ratelimit.py`)
but not for API endpoints in general. MCP tool calls can be chatty (LLM retries, tool loops).

**Required:** Per-token rate limit on the `/mcp` endpoint. The token's `last_used_at` update has
a 1-minute resolution (`_LAST_USED_RESOLUTION`) to avoid write pressure — this is fine for
auditing but rate limiting needs a separate counter.

---

#### I3 — `ApiTokenRead` does not expose whether the token has been used for MCP

**Improvement:** Add a `last_mcp_use_at` field (nullable datetime) to `ApiToken` and `ApiTokenRead`.
Updated when any MCP tool call is made. Lets users and admins see "this token was last used as
an MCP connector on Oct 26."

---

#### I4 — Token description / label is not stored

**Current state:** `ApiToken.name` is a free-form string. There is no `description` or `label`
to say what the token is for ("Lovable connector for customer-api", "Claude Code integration").

**Improvement:** Add an optional `description: str | None` column (max 255 chars). Helps
org admins identify tokens without needing the audit log.

---

#### I5 — `GET /account/tokens` does not expose `mcp_enabled` on the project member record

When a user creates an MCP token for a project, they need to know whether the project owner has
granted them MCP access before the token will work. The token creation should succeed (it's their
own token), but the response (or a warning) should tell them if MCP is currently disabled for
them on that project. Without this, users will create tokens and be confused when MCP tools fail.

---

#### I6 — No `/.well-known/oauth-protected-resource` endpoint

**From MASTER_PLAN §WP6:**
> The protected-resource metadata endpoint is added now so clients can discover that PATs are
> accepted.

**RFC 9728** defines `/.well-known/oauth-protected-resource`. MCP clients that follow the spec
will try to fetch this before attempting OAuth. We need to serve a minimal response:
```json
{
  "resource": "https://builder.example.com",
  "bearer_methods_supported": ["header"],
  "authorization_servers": []
}
```
Without this, some MCP clients will fail or silently fall back to OAuth (which we don't support
yet).

---

#### I7 — `SCOPE_MCP_WRITE` should require `editor` or higher, not just any member

**Current state:** The MCP write tools (`create_entity`, `add_field`, etc.) will need to check
that the user has at least `editor` on the project. This is the same as the REST API requirement
for write endpoints. The MCP guard must enforce this — the `guard` dependency in `security.py`
won't run for MCP tool calls (see G3).

---

### TIER 4 — NOTES / RESEARCH FINDINGS (informational, not bugs)

#### N1 — How Lovable's custom MCP actually works (from L1 in MASTER_PLAN)

Researched and confirmed: Lovable's "custom MCP" is configured per user in their settings
under "Integrations". It accepts a URL + optional auth (header, bearer token, or no auth).
The transport is **Streamable HTTP** (the current MCP spec, post-2025). Lovable calls
`list_tools`, then calls individual tools during the chat. It does NOT implement OAuth PKCE
itself — it just passes a bearer token in the `Authorization` header if you configure one.

This confirms: **PAT with `mcp:read` scope, passed as `Authorization: Bearer bb_pat_...`
is exactly the right v1 approach for Lovable.**

#### N2 — MCP spec transport (Streamable HTTP vs SSE)

The current MCP spec (2025-11-05 revision as of late 2025) specifies **Streamable HTTP** as the
primary transport. The older SSE-only transport is deprecated. The official Python SDK
(`mcp>=1.0`) supports `streamable_http_app()` which is a Starlette app you can mount in FastAPI
with `app.mount("/mcp", mcp_app)`. This is the right approach.

#### N3 — Tool poisoning / prompt injection

MCP server outputs are rendered into the LLM's context. If our tools return user-authored content
(entity names like `"'; DROP TABLE users; --"`, field descriptions with `<script>` tags), these
appear verbatim in the model's prompt. This doesn't execute code but can confuse the model or
be used for indirect prompt injection. Mitigations already in the plan: cap output size, strip
control characters. Additionally: never return raw user-authored content without length-capping
and escaping.

#### N4 — The `mcp` package decision

`D4` in MASTER_PLAN: `mcp` package (official Anthropic SDK). Current version: `mcp>=1.3`.
It supports: FastMCP (higher-level), low-level server, Streamable HTTP transport, in-process
client for testing. Use `FastMCP` for tool definition (decorator-based, automatic schema
generation), `streamable_http_app()` for mounting.

#### N5 — MCP `list_projects` tool must not return every member project when token is pinned

This is the concrete MCP-layer enforcement of B4/G4. The `list_projects` MCP tool must call
the project service with the principal's `token_project_id` filter. If the token is pinned to
one project, `list_projects` returns exactly one entry (or an empty list if the user is somehow
no longer a member).

#### N6 — `get_openapi` returns the *generated* API's OpenAPI spec

This is **not** the builder's own `/openapi.json`. It calls `generator.generate(spec)` in
read-only mode (or reads the last generation snapshot from `generations`) and returns the
generated project's OpenAPI. Lovable uses this to know the routes, schemas, and auth model of
the backend it is building a frontend for. This is the highest-value tool in the toolset.

#### N7 — `get_frontend_contract` is new, not a simple passthrough

This tool synthesises information from multiple sources:
- The generated OpenAPI (route shapes, schemas)
- The auth block (what login flow to use, token format, endpoints)
- The pagination convention (`{items, total, limit, offset}`)
- The error format (`{code, message, details[]}`)
- The project's roles (for auth-protected routes)

It produces a human-readable + LLM-digestible contract document. This is the tool that lets
Lovable build a correct frontend without manually reading every API detail.

#### N8 — MCP `generate_project` returns a download link, not bytes

A zip file is 10–50 MB. It cannot be returned inline in an MCP tool response without overwhelming
the LLM's context. The tool creates a generation record (same as `GET /projects/{id}/generate/download`)
and returns a signed URL or a token-authenticated download URL. The user then downloads the zip
themselves. This is the correct pattern.

---

## 4. Full design for WP6 (incorporating all findings above)

### 4.1 Data model changes needed

**Migration WP6 (new):**

```sql
-- 1. Add mcp_enabled to project_members (per B2)
ALTER TABLE project_members
    ADD COLUMN mcp_enabled BOOLEAN NOT NULL DEFAULT FALSE;

-- 2. Add mcp:generate to valid scopes (code change, not DB)

-- 3. Add description to api_tokens (per I4)
ALTER TABLE platform_api_tokens
    ADD COLUMN description VARCHAR(255);

-- 4. Add last_mcp_use_at to api_tokens (per I3)
ALTER TABLE platform_api_tokens
    ADD COLUMN last_mcp_use_at TIMESTAMP WITH TIME ZONE;
```

### 4.2 Code changes needed before building the MCP endpoint

Priority order:

1. **Fix B1:** Add `SCOPE_MCP_GENERATE` to `platform_authz.py`
2. **Fix B4/G4:** Verify and fix `ProjectService.list()` to honour `token_project_id`
3. **Add migration** for `project_members.mcp_enabled`
4. **Update `MemberService`** to accept and return `mcp_enabled`
5. **Update member endpoints** (`POST /projects/{id}/members`, `PATCH .../members/{user_id}`)
   to expose `mcp_enabled`
6. **Add G5 endpoints:** `GET /projects/{id}/tokens`, `DELETE /projects/{id}/tokens/{tid}`
7. **Fix G6:** Add `via` filter to `audit_service.search()` and `GET /admin/audit`
8. **Add I6:** `GET /.well-known/oauth-protected-resource`

### 4.3 The MCP server itself

```
app/api/mcp.py              # FastMCP instance + tool definitions + mount
app/services/mcp_service.py # Tool implementations (call into existing services)
```

**Mount point:**
```python
# app/main.py
from app.api.mcp import mcp_app
app.mount("/mcp", mcp_app)
```

**Auth flow for the MCP endpoint:**
```
MCP client sends: Authorization: Bearer bb_pat_<public_id>_<secret>
→ MCP middleware calls access_service.principal_from_api_token()
→ checks mcp:read (or mcp:write / mcp:generate) scope
→ checks project membership
→ checks project_members.mcp_enabled for the requesting user on the target project
→ audits the tool call as action="mcp.tool_call"
```

**Tools (read, scope `mcp:read`):**
```
list_projects          → projects the token's user is a member of AND mcp_enabled=True for them
get_project_spec       → assembled spec JSON for one project
get_data_model         → entities + fields + relations (human-readable summary)
get_openapi            → generated project's OpenAPI 3.1 JSON
get_auth_model         → auth block summary (provider, flows, token format)
get_frontend_contract  → synthesised contract: routes + auth flow + pagination + errors + roles
get_deploy_info        → cloud + env info (no secrets)
validate_spec          → run the validator, return issues list
```

**Tools (write, scope `mcp:write`, requires `editor` or higher member role):**
```
create_entity          → create an entity (name + description only; fields added separately)
add_field              → add a field to an entity
add_relation           → create a relation between two entities
set_permissions        → set RBAC permissions on an entity operation
```

**Tools (generate, scope `mcp:generate`, requires `editor` or higher):**
```
generate_project       → trigger generation, return download URL (not bytes)
```

**Resources:**
```
spec://{project_slug}     → spec JSON (readable by mcp:read)
openapi://{project_slug}  → generated OpenAPI (readable by mcp:read)
```

**Prompts:**
```
build_admin_dashboard(project_id)  → "Here is the spec for project X. Build an admin dashboard..."
```

### 4.4 The `Integrations` page (dashboard, WP7 area)

Under `Ship → Integrations`:
- "Create MCP token" button → opens token create dialog pre-filled with `mcp:read` scope, project pin optional
- "Copy connector config" → generates the JSON snippet for Lovable / Claude / Cursor
- Usage log → filtered view of `platform_audit_log` where `action LIKE 'mcp.%'`
- Per-token last MCP use timestamp
- "Revoke" button per token

---

## 5. Complex worked example

This covers the deepest aspects: org admin, per-user MCP grant, pinned token, scope enforcement,
audit trail, and cross-user isolation.

### Setup

```
Platform: BackendBuilder SaaS
Org: Acme Corp

Users:
  priya@acme.com   platform_role=customer (acting as org admin = project owner on all 8 projects)
  dev1@acme.com    platform_role=customer
  dev2@acme.com    platform_role=customer
  dev3@acme.com    platform_role=customer

Projects and membership + MCP grants:
  customer-api:
    priya  (owner,  mcp_enabled=true)
    dev1   (owner,  mcp_enabled=true)   ← dev1 CAN use MCP here
    dev2   (editor, mcp_enabled=false)  ← dev2 is a member but CANNOT use MCP

  billing-service:
    priya  (owner,  mcp_enabled=true)
    dev1   (viewer, mcp_enabled=false)  ← dev1 is a viewer, MCP disabled
    dev3   (owner,  mcp_enabled=true)

  auth-service:
    priya  (owner,  mcp_enabled=true)
    dev1   (editor, mcp_enabled=true)   ← dev1 CAN use MCP here
    dev2   (editor, mcp_enabled=true)
    dev3   (viewer, mcp_enabled=false)

  analytics-api:
    priya  (owner,  mcp_enabled=true)
    dev2   (owner,  mcp_enabled=true)

  notification-svc:
    priya  (owner,  mcp_enabled=true)
    dev3   (editor, mcp_enabled=false)  ← dev3 edits it but MCP is off

  file-service:
    priya  (owner,  mcp_enabled=true)
    dev1   (owner,  mcp_enabled=true)   ← dev1 CAN use MCP here
    dev3   (viewer, mcp_enabled=false)

  payment-gateway:
    priya  (owner,  mcp_enabled=true)
    dev2   (editor, mcp_enabled=false)
    dev3   (owner,  mcp_enabled=true)

  admin-portal:
    priya  (owner,  mcp_enabled=true)
    dev1   (owner,  mcp_enabled=true)   ← dev1 CAN use MCP here
```

### Tokens created

```
Token T1: dev1@acme.com
  scopes=[mcp:read, mcp:write]
  project_id=NULL (not pinned — sees all MCP-enabled projects for dev1)
  expires_in_days=90

Token T2: dev1@acme.com
  scopes=[mcp:read]
  project_id=customer-api-uuid (pinned — only sees customer-api)
  expires_in_days=30

Token T3: dev2@acme.com
  scopes=[mcp:read]
  project_id=NULL
  expires_in_days=90

Token T4: dev3@acme.com
  scopes=[mcp:read, mcp:generate]
  project_id=billing-service-uuid (pinned)
  expires_in_days=60
```

### Trace of every scenario

---

**Scenario 1: dev1 connects T1 (unpinned) to Lovable → calls `list_projects`**

```
Request: MCP tool call list_projects
Auth: Bearer T1 (bb_pat_...)
→ principal_from_api_token() → Principal(user=dev1, scopes={mcp:read, mcp:write}, token_project_id=None)
→ MCP guard: scope check → mcp:read ✓
→ list_projects service:
    SELECT project_id FROM project_members
    WHERE user_id = dev1.id AND mcp_enabled = TRUE
→ Returns: [customer-api, auth-service, file-service, admin-portal]
   (NOT billing-service: mcp_enabled=False for dev1 there)
   (NOT analytics-api, notification-svc, payment-gateway: dev1 not a member)
→ Audit: action="mcp.tool_call", tool="list_projects", result=ok, actor=dev1, via=api_token
```

Lovable sees 4 projects. Dev1 picks `customer-api`.

---

**Scenario 2: dev1 uses T1 → calls `get_openapi` on `customer-api`**

```
Request: MCP tool call get_openapi(project_id="customer-api-uuid")
Auth: Bearer T1
→ Principal: dev1, scopes={mcp:read, mcp:write}, token_project_id=None
→ MCP guard: scope check → mcp:read ✓
→ Project existence check: customer-api exists ✓
→ Membership check: dev1 is owner of customer-api ✓
→ MCP grant check: project_members(dev1, customer-api).mcp_enabled = True ✓
→ Call generator.generate(spec, dry_run=True) or read last generation snapshot
→ Return: { "openapi": "3.1.0", "paths": { ... }, "components": { ... } }
→ Audit: action="mcp.tool_call", tool="get_openapi", project_id=customer-api-uuid, result=ok
```

---

**Scenario 3: dev1 uses T1 → tries `get_openapi` on `billing-service`**

```
Request: MCP tool call get_openapi(project_id="billing-service-uuid")
Auth: Bearer T1
→ Principal: dev1, scopes={mcp:read, mcp:write}, token_project_id=None
→ MCP guard: scope check → mcp:read ✓
→ Project existence check: billing-service exists ✓
→ Membership check: dev1 is viewer of billing-service ✓ (member, so not a 404)
→ MCP grant check: project_members(dev1, billing-service).mcp_enabled = FALSE ✗
→ Response: 403 {"code": "mcp_not_granted", "message": "MCP access not enabled for you on this project"}
→ Audit: action="access.denied", why="mcp_not_granted", project_id=billing-service-uuid, result=denied
```

Dev1 cannot use MCP on billing-service even though they're a member.

---

**Scenario 4: dev1 uses T2 (pinned to customer-api) → calls `list_projects`**

```
Request: MCP tool call list_projects
Auth: Bearer T2 (pinned to customer-api)
→ Principal: dev1, scopes={mcp:read}, token_project_id=customer-api-uuid
→ list_projects service:
    FILTER: only customer-api (because token_project_id is set)
    ALSO CHECK: project_members(dev1, customer-api).mcp_enabled = True ✓
→ Returns: [customer-api]  ← exactly 1 project
→ Audit: action="mcp.tool_call", tool="list_projects", result=ok
```

Lovable only sees one project because the token is pinned.

---

**Scenario 5: dev2 uses T3 (unpinned) → calls `list_projects`**

```
Request: MCP tool call list_projects
Auth: Bearer T3
→ Principal: dev2, scopes={mcp:read}, token_project_id=None
→ list_projects service:
    SELECT project_id FROM project_members
    WHERE user_id = dev2.id AND mcp_enabled = TRUE
→ Returns: [auth-service, analytics-api]
   (NOT customer-api: mcp_enabled=False for dev2 there, even though dev2 is an editor)
   (NOT payment-gateway: dev2 is editor but mcp_enabled=False)
→ Audit: ...
```

Dev2 is an editor on customer-api but still cannot see it via MCP — priya (org admin/owner)
hasn't enabled MCP for dev2 on that project.

---

**Scenario 6: dev2 uses T3 → tries `add_field` on `auth-service` (write tool)**

```
Request: MCP tool call add_field(project_id="auth-service-uuid", entity="User",
                                  field={name: "avatar_url", type: "string"})
Auth: Bearer T3 (scopes={mcp:read})
→ Principal: dev2, scopes={mcp:read}, token_project_id=None
→ MCP guard: tool requires mcp:write scope
→ Scope check: mcp:read ∉ {mcp:write} → FAIL
→ Response: 403 {"code": "insufficient_scope", "message": "this tool requires mcp:write scope"}
→ Audit: action="access.denied", why="scope", result=denied
```

Dev2's token is read-only. They need to create a new token with `mcp:write` to use write tools.

---

**Scenario 7: dev3 uses T4 (pinned to billing-service, has mcp:generate) → calls `generate_project`**

```
Request: MCP tool call generate_project(project_id="billing-service-uuid")
Auth: Bearer T4 (pinned to billing-service, scopes={mcp:read, mcp:generate})
→ Principal: dev3, scopes={mcp:read, mcp:generate}, token_project_id=billing-service-uuid
→ MCP guard: tool requires mcp:generate ✓
→ Pinned project check: billing-service-uuid == billing-service-uuid ✓
→ Membership check: dev3 is owner of billing-service ✓
→ MCP grant check: project_members(dev3, billing-service).mcp_enabled = True ✓
→ Role check for generation: owner ≥ editor ✓
→ Trigger generation → create Generation record → return download URL
→ Audit: action="mcp.tool_call", tool="generate_project", project_id=billing-service, result=ok
         + action="generation.create" (from generation service)
```

Dev3 gets a download URL in the MCP response. They open it in their browser.

---

**Scenario 8: dev1 (with T1) tries to `generate_project` on `customer-api`**

```
Request: MCP tool call generate_project(project_id="customer-api-uuid")
Auth: Bearer T1 (scopes={mcp:read, mcp:write} — NO mcp:generate)
→ MCP guard: tool requires mcp:generate
→ Scope check: {mcp:read, mcp:write} ∩ {mcp:generate} = ∅ → FAIL
→ Response: 403 {"code": "insufficient_scope", "message": "this tool requires mcp:generate scope"}
```

Even though dev1 has mcp:write, generate is intentionally a separate scope (a zip leaves the
platform — it's a different trust level).

---

**Scenario 9: priya (org admin) audits MCP activity on customer-api**

```
Priya opens the builder dashboard → Project: customer-api → Integrations tab
→ Calls: GET /projects/customer-api-uuid/audit?action=mcp.tool_call
→ Service filters platform_audit_log WHERE project_id=customer-api AND action='mcp.tool_call'
→ Returns:
  [
    {at: "2026-10-26T09:00", actor: "dev1@acme.com", via: "api_token",
     detail: {tool: "list_projects", result: "ok"}},
    {at: "2026-10-26T09:01", actor: "dev1@acme.com", via: "api_token",
     detail: {tool: "get_openapi", result: "ok"}},
    {at: "2026-10-26T09:05", actor: "dev1@acme.com", via: "api_token",
     detail: {tool: "add_field", entity: "User", field: "avatar_url", result: "ok"}},
    ...
    {at: "2026-10-26T09:10", actor: "dev2@acme.com", via: "api_token",
     detail: {tool: "get_openapi", result: "denied", why: "mcp_not_granted"}},
  ]
```

Priya sees dev2 tried to use MCP and was blocked. She can now decide to grant or keep it denied.

---

**Scenario 10: priya revokes dev1's T1 token from the project tokens view**

```
GET /projects/customer-api-uuid/tokens
→ Auth: priya's session (owner role)
→ Returns: [T1 (dev1, mcp:read+write, unpinned), T2 (dev1, mcp:read, pinned here)]

DELETE /projects/customer-api-uuid/tokens/{T1.id}
→ priya revokes T1 for customer-api
→ Audit: action="token.revoke_by_project_owner", actor=priya, target_token=T1.public_id,
         project_id=customer-api
→ T1.revoked_at = now()
```

Note: T1 is not pinned to customer-api specifically — revoking it removes dev1's MCP access
everywhere (all 4 projects where dev1 has MCP enabled). This is acceptable behaviour and
should be documented: "Revoking a token at the project level revokes the token entirely if
it is not pinned to this project." Alternatively, pinned-token revocation at the project level
is the safer UX and should be the default recommended approach.

---

## 6. Summary of all items requiring action before WP6 ships

### Must do (blockers):
- [ ] B1: Add `SCOPE_MCP_GENERATE` to `platform_authz.py` and `VALID_SCOPES`
- [ ] B2: Add `mcp_enabled` to `ProjectMember` (migration + model + service + API)
- [ ] B3: Add `GET /admin/users/{user_id}/tokens` and revoke endpoint
- [x] B4: `list_projects` pinned-token filtering — already correct in `ProjectService.list()`
- [ ] B5: Add `mcp` package to `pyproject.toml` (pinned)

### Should do (gaps):
- [ ] G1: Document org-admin limitation; defer full org model to WP10
- [ ] G2: Add `action="mcp.tool_call"` audit events in MCP layer
- [ ] G3: Build MCP-specific auth middleware (not the REST guard)
- [ ] G5: Add `GET/DELETE /projects/{id}/tokens` (project-scoped token management)
- [ ] G6: Add `via` filter to `audit_service.search()` and `GET /admin/audit`

### Nice to have (improvements):
- [ ] I1: Warn on `mcp:*` token without project pin for viewer role
- [ ] I2: Per-token rate limiting on `/mcp`
- [ ] I3: Add `last_mcp_use_at` to `ApiToken`
- [ ] I4: Add `description` to `ApiToken`
- [ ] I5: Return MCP grant status in token create response
- [ ] I6: Add `GET /.well-known/oauth-protected-resource`
- [ ] I7: Enforce `editor` or higher for `mcp:write` tools in MCP middleware

---

## 7. Order of implementation (recommended)

1. **Pre-work (1–2 hours):** B1, B4/G4, I6 — code-only changes, no migration
2. **Migration WP6 (1 hour):** B2 (`mcp_enabled`), I3 (`last_mcp_use_at`), I4 (`description`)
3. **Service changes (2–3 hours):** B2 service/API, G5 endpoints, G6 audit filter, B3 admin endpoints
4. **MCP server itself (4–6 hours):** `app/api/mcp.py`, `app/services/mcp_service.py`, auth middleware, all tools, resources, prompt
5. **Tests (2–3 hours):** Scope enforcement, cross-user isolation, mcp_enabled gate, pinned token, audit events, oversize output
6. **Dashboard Integrations page (2–3 hours):** Token creation UI, connector config copy, usage log, MCP enable/disable toggle per member

**Total estimated: 12–18 hours of focused implementation.**

---

*End of WP6 research document. Review, correct and then I'll proceed with implementation in the order above.*
