# Connecting an AI client to BackendBuilder over MCP

BackendBuilder exposes an MCP server (Streamable HTTP) at `/mcp` on the platform API. An AI client that knows
nothing about the platform can build a complete backend with it: create the project, model data, roles and
permissions, add behaviour and packs, start a preview, validate and generate. Everything a human must enter
(credentials) is listed for them, never accepted or returned by a tool.

## 1. Connect

1. Sign in to the dashboard, open **Account > API tokens** and create a token (`bb_pat_...`). Tick only the scopes you need (section 2).
   A token can be pinned to one project; a pinned token cannot create projects.
2. In the project's member settings make sure **MCP access** is enabled for your membership (projects created
   with `create_project` enable it for their creator).
3. Point the client at `https://<api-host>/mcp` with header `Authorization: Bearer bb_pat_...`.
   Claude Code example: `claude mcp add --transport http builder https://<api-host>/mcp --header "Authorization: Bearer bb_pat_..."`.
4. The server also offers the prompt `build-a-backend`; the first tool to call is `get_started`.

## 2. Scopes

| Scope | Allows | Notes |
|---|---|---|
| `mcp:read` | every read tool (spec, model, status, secrets checklist, metrics, config, history) | implies nothing else |
| `mcp:write` | create_project, data model, roles, permissions, auth config, behaviour, config sections, metrics and reports | needs editor+ role on the project |
| `mcp:generate` | `generate_project` | renders the zip, returns a download path |
| `mcp:preview` | create/get/kill preview, preview logs | a preview-only token reaches no other tool; the preview token is returned once |
| `mcp:destructive` | removals, `put_packs`, and confirming access-widening edits (`confirm_weakening`) | dry run is the default |

Every tool also checks: the token scope, your project role, organisation membership, the per-member MCP grant,
the organisation plan, and the project pin (if any). Tool output never contains another tenant's data.

## 3. Tools (44)

| Tool | Scope | What it does |
|---|---|---|
| `describe_platform` | `mcp:read` | What this platform can build and what it cannot, from the live registries: Spec sections and the tool that edits each, domain packs (money, operations |
| `get_started` | `mcp:read` | Ordered playbook from an empty organisation to a generated backend, naming the exact tool for each step, plus the rules (secrets, dry runs, errors) |
| `list_projects` | `mcp:read` | Projects you can reach with this token, with your role |
| `get_project_spec` | `mcp:read` | The full spec of a project (capped) |
| `get_data_model` | `mcp:read` | Entities, fields, relations |
| `get_openapi` | `mcp:read` | OpenAPI of the backend the current spec would generate |
| `get_auth_model` | `mcp:read` | Get authentication configuration for a project (provider, flows, token format) |
| `get_frontend_contract` | `mcp:read` | Get the frontend contract: routes, auth flow, pagination conventions, error shapes, and roles |
| `get_deploy_info` | `mcp:read` | Get deployment configuration for a project (cloud, region, environments) |
| `list_secrets_needed` | `mcp:read` | What only a human can enter for this project (SMTP/SMS, Stripe, Keycloak/Okta, storage and cloud keys ...): names and where to enter them in the dashb |
| `validate_spec` | `mcp:read` | Validation issues of the current spec |
| `list_op_types` | `mcp:read` | List the spec operation types with their payload schemas and which are destructive |
| `list_spec_history` | `mcp:read` | Recent spec changes (for undo) |
| `get_project_status` | `mcp:read` | The dashboard's readiness board: what is configured, issues per section, and the one next step, plus `missing` (what is left, who can do it: tool or h |
| `list_roles_and_permissions` | `mcp:read` | Roles (with self_assignable, invite_only, position) and the entity x operation permission matrix of a project |
| `list_generations` | `mcp:read` | Past generations of the project |
| `get_config_section` | `mcp:read` | Read the saved settings of one section: payments, storage, documents, observability or deployment (never any secret) |
| `list_metrics` | `mcp:read` | List the project's metric definitions (the metrics layer: one definition serves the project_id<uuid> |
| `get_metric_value` | `mcp:read` | Live value of one metric (redacted for your project role like the dashboard) |
| `list_reports` | `mcp:read` | List the project's scheduled reports (name, metric keys, cron schedule, timezone) |
| `create_entity` | `mcp:write` | Create a new entity in a project |
| `add_field` | `mcp:write` | Add a field to an entity |
| `add_relation` | `mcp:write` | Add a relation between entities |
| `set_permissions` | `mcp:write` | Save one entry of the role permission matrix: which roles may do `operation` (list/get/create/update/replace/delete/head) on an entity |
| `create_project` | `mcp:write` | Create a new project (you become its owner, MCP is enabled for you) |
| `create_role` | `mcp:write` | Create a role |
| `update_role` | `mcp:write` | Change an existing role by name |
| `set_auth_config` | `mcp:write` | Create or update sign-in settings (enabled, token lifetimes, registration rules, magic link, rate limits, app_name ...) |
| `set_authorization` | `mcp:write` | Replace the authorization block (model, policies, attachments, field_access) like the dashboard's Authorization page |
| `apply_op` | `mcp:write` | Apply ONE typed spec operation (see list_op_types for the payload schemas): add_entity, update_entity, add_field, update_field, add_relation, update_r |
| `put_behavior_block` | `mcp:write` | Save one behaviour block: events, providers, notifications, jobs, workflows, api_edge, webhooks (hook_effects: project owner only) |
| `undo_last_change` | `mcp:write` | Undo your own most recent MCP change |
| `redo_last_change` | `mcp:write` | Redo the change that was just undone |
| `set_config_section` | `mcp:write` | Save the NON-SECRET settings of payments, storage, documents, observability or deployment (same validation as the dashboard; the whole section is repl |
| `define_metric` | `mcp:write` | Create or update (by key) a metric definition: {entity, agg: count/sum/avg/min/max, field, label, filter, group_by} |
| `define_report` | `mcp:write` | Create a scheduled report over existing metric keys (5-field cron schedule), or update one when report_id is given |
| `run_report` | `mcp:write` | Run a report now and store the run (counts toward the org's reports.runs usage) |
| `create_preview` | `mcp:preview` | Start a throwaway sandbox preview of the project's current spec so you can see the generated API run |
| `get_preview` | `mcp:preview` | State of one preview (starting, running, sleeping, failed, killed, expired) with its expiry; omit preview_id to list this project's previews |
| `get_preview_logs` | `mcp:preview` | Last log lines of a running preview (bounded snapshot, credentials redacted) |
| `kill_preview` | `mcp:preview` | Stop a preview and free its sandbox (its data is discarded) |
| `generate_project` | `mcp:generate` | DESTRUCTIVE |
| `apply_destructive_op` | `mcp:destructive` | Remove/rename ops (remove_field, remove_entity ...); dry run by default |
| `put_packs` | `mcp:destructive` | Replace the domain packs (money, operations, booking, ai); dry run by default |

`describe_platform` and each tool's help give example arguments and the usual next tool.
Failures are JSON: `{"error": {"code", "message", "status", "hint", "next_tools"}}`.

## 4. What an AI cannot do here (by design)

- Enter or read credentials: SMTP/SMS passwords, Stripe/GitHub/Twilio/Okta/Keycloak keys, key files. Secret-looking keys and values are refused with `secret_not_allowed`; use `list_secrets_needed` to tell the user what to enter and where (dashboard).
- Switch payments or storage on (a dashboard action), delete projects, or widen access without `mcp:destructive` + `confirm_weakening`.

## 5. Example conversation

> **User:** Build me a backend for a small clinic: patients, doctors, appointments. Receptionists book, doctors confirm and complete.
>
> **AI:** `get_started` -> `describe_platform` -> `create_project {"name": "Clinic Booking"}`
> then `create_entity` + `add_field` for Patient / Doctor / Appointment (status is an enum), `add_relation` (ids come from `create_entity`),
> `set_auth_config` (enabled, app_url, smtp_config host/from), `create_role` x4, `set_permissions` per entity and operation,
> `apply_op set_section` for the Appointment state machine and a `slot_minutes` setting, `put_behavior_block events`,
> `put_packs` (booking; dry run first, then `dry_run=false` with `mcp:destructive`), `set_config_section observability`,
> `define_metric appointments_total`.
>
> **AI:** `validate_spec` -> `get_project_status` ("nothing missing except secrets a human must enter") -> `list_secrets_needed`
> -> `create_preview` (poll `get_preview` until running, `get_preview_logs`, `kill_preview`) -> `generate_project`.
>
> **AI to user:** "Your backend is generated. Before it can send e-mail, enter `SMTP_USERNAME` and `SMTP_PASSWORD` in the dashboard (project > Settings > Sign-in)."

This journey is a test: `tests/api/test_mcp_journey.py`.
