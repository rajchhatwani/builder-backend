# Master plan: platform auth, authorization models, observability, deployment, PDF, MCP, docs

Written 2026-10-24 for an unattended 5-8 hour run. **This file is the resume point**: status of every work
package is tracked in section 4, limitations in section 6. A new chat (or a context compaction) must read this
file first, then the package's own section, then `git status`. Companion plans: `VISION.md`, `PLAN.md`,
`KEYCLOAK_PLAN.md`, `PAYMENTS_PLAN.md`, `STORAGE_PLAN.md`. Status legend: `[ ]` todo, `[~]` in progress, `[x]` done,
`[!]` blocked / needs the owner.

## 0. Ground rules for the run

1. **One package at a time, finished before the next**: research -> decisions -> implement -> tests -> UI ->
   self-review (the "second look" in section 3) -> update this file. Never leave a package half-wired; if time
   runs out, the last finished package is the stopping point and the next one is described, not started.
2. **Order = priority** (owner's request: backend, deployment and critical APIs first). Section 4 is the cut line.
3. **Deterministic, no AI in the generated output.** Same spec -> same bytes. No clock/randomness in the generator.
4. **Fail closed, default deny.** Anything unknown, unconfigured or ambiguous is refused, not allowed.
5. **No secret ever in the zip, the logs, the spec or the browser.** Env vars only; the builder keeps only what
   it must, encrypted (`app/core/crypto.py`).
6. **Libraries**: stdlib first. Previously approved: `cryptography`, `redis`, `boto3`. The owner delegated the
   choice for this run ("I trust you"), so new dependencies are allowed **only where a package below names them**,
   each is listed in section 5 as a veto-able decision, and each is pinned and justified. Anything else: ask.
7. **Flag, do not hide.** Every limitation, odd finding or risk goes into section 6 the moment it is found, with
   severity and what it blocks. Blockers that endanger user data or money are fixed before the feature that
   exposed them.
8. **Nothing outward-facing without the owner**: no commits, no pushes, no real cloud/provider calls, no
   publishing. The working tree is left uncommitted for review (it already holds earlier uncommitted work).
9. **Verify with the real thing where possible** (Docker stack, testcontainers, `terraform validate` in a
   container). Where a real provider/cloud cannot be reached, the result is labelled **unverified** in
   section 6, never "done".

## 1. Where we are (audit at start, 2026-10-24)

Builder = FastAPI + Postgres API (`app/`), spec -> generator (`app/core/generator`, feature modules `crud`,
`docker`, `tests`, `auth`, `keycloak`, `payments`, `storage`), React dashboard (`frontend/`, hash router,
flat 8-item sidebar). Generated projects are FastAPI + SQLAlchemy + Alembic + Docker.

Findings that shape the plan:

- **F1 (critical): the builder API has no authentication and projects have no owner.** Anyone who can reach
  :8000 can read/modify/generate every project and call `PUT /auth/secrets` (stores encrypted SMTP/SMS
  secrets). Fine on a laptop, unacceptable as a platform. Fixed first (WP1).
- F2: the dashboard sidebar is one flat list that already has 8 entries; every new feature would add another.
  Needs a grouped information architecture (WP1 shell work, finished in WP7).
- F3: generated authorization is RBAC + row rules only (`RowRule`: owner, role_scoped, tenant, custom_filter).
  No attribute conditions, no named policies, no explanation of "which model should I use".
- F4: generated projects have structlog JSON logs but no trace/metric export, no correlation id propagation,
  no collector.
- F5: generated `docker-compose` exists; no CI/CD, no cloud IaC, no environment concept.
- F6: Lovable's custom MCP is a **chat context connector** (see section 6, L1).

## 2. Work packages in priority order

Each package lists: goal, research to do first, design, deliverables, tests, UI, done-when.

### WP0 - Baseline and hygiene (30 min)
- Run unit + api tests to know the starting state (red tests found now are not mine later). Record result here.
- Create `docs/` skeleton and the limitations register (section 6).
- Done-when: baseline recorded in section 4.

### WP1 - Platform accounts, IAM and the admin/customer split (P0, backend + shell UI)
**Goal.** The builder becomes a multi-user platform. Two separate surfaces:
- **Customer app** (`/app`, existing dashboard): sign up / log in, own projects, API tokens, invitations.
- **Admin console** (`#/admin`, `/api/admin/*`, separate guard): platform operators only - user management,
  suspend/restore, role assignment, audit log, system settings, usage overview. Customers never see it; the
  API rejects customer tokens on admin routes (separate audience claim `aud=admin`, separate permission set).

**Research first**: OWASP ASVS V2/V3 (password, session), OWASP cheat sheets (Password Storage, Session
Management, JWT), token refresh rotation + reuse detection, httpOnly cookie vs memory token for SPAs, CSRF
with cookie refresh, PAT design (prefix + hash, shown once), account lockout vs rate limit, audit log design.

**Design.**
- Tables: `users` (email unique citext-style lower-cased, password hash scrypt N=2^15 as in generated auth,
  status active|suspended|pending, platform_role, mfa later), `sessions`/`refresh_tokens` (hashed, family id,
  rotated on use, reuse of a rotated token kills the family), `api_tokens` (prefix `bb_pat_`, sha256 only stored,
  scopes, expiry, last_used, revoked), `project_members` (project_id, user_id, role owner|editor|viewer),
  `audit_log` (append-only: actor, action, target, ip, request id, result; no PII beyond ids/emails).
  `projects.owner_id` added; **existing rows are backfilled to a bootstrap admin** (see below).
- Platform roles: `platform_admin`, `platform_support` (read-only admin), `customer`. Project roles: `owner`,
  `editor`, `viewer`. The permission matrix is a data table in code and enforced by one dependency
  (`require(permission, project_id=...)`) - the **platform eats its own dog food**: same policy engine shape as
  WP2 (RBAC + ownership attribute), so one mental model.
- Tokens: access JWT 15 min (HS256 key from `BUILDER_SECRET_KEY`, startup refuses a missing/short key outside
  `local`), refresh opaque 14 days rotating, in an httpOnly SameSite=Strict cookie scoped to `/api/auth`;
  access token held in memory by the SPA. Bearer PAT accepted by the same dependency (scopes limit it).
- First admin: created from env (`BUILDER_BOOTSTRAP_ADMIN_EMAIL` + `BUILDER_BOOTSTRAP_ADMIN_PASSWORD`, applied
  once at startup if no admin exists; never logged). Registration is open by default but configurable
  (`BUILDER_SIGNUP_MODE=open|invite|closed`).
- Hardening: per-IP and per-account throttling (in-process + DB counter; limitation noted), constant-time
  compare, generic login errors, no user enumeration on login/reset, password policy (length >= 12, breached
  list check deferred - L5), security headers middleware, CORS allow-list only, request-size limit, audit every
  auth and admin event.
- Every existing router is guarded; every project-scoped route resolves membership first (404 for projects the
  caller cannot see, not 403, to avoid enumeration).
- Existing secrets service: access limited to project owner/editor; value never returned (already true).

**Deliverables.** models + alembic migration, `app/core/platform_authz.py`, services, routers
`/api/auth/*` (register, login, refresh, logout, me, change password), `/api/tokens`, `/api/admin/*`,
`/api/projects/{id}/members`; seed script updated; Postman collection updated.
**Tests.** unit (hashing, token rotation/reuse, permission matrix as a decision table, PAT scopes), API
(every route x every role: allowed/denied matrix generated from the matrix itself so a new route without a rule
fails the test), security (cookie flags, lockout, enumeration, replayed refresh, admin token on customer route and
vice versa, IDOR across two customers).
**UI.** login/register screens, session handling in `client.ts`, account menu, tokens page, members dialog,
**admin console** as its own layout (different chrome, color band) with Users, Audit log, Settings.
**Done-when**: no route is reachable unauthenticated except health + auth endpoints (asserted by a test that walks
the OpenAPI schema), IDOR tests green, UI login works against the Docker stack.

### WP2 - Generated-project authorization: RBAC, ABAC, PBAC out of the box + recommender (P0)
**Goal.** A project picks `authorization.model = rbac | abac | pbac` (default `rbac`, unchanged behaviour).
Pure code generation, no AI. Plus a deterministic **recommender** ("which model fits my project?").

**Research first**: NIST SP 800-162 (ABAC definitions: subject/object/action/environment attributes, PEP/PDP),
XACML combining algorithms (deny-overrides), OWASP Authorization cheat sheet, AWS Cedar / OPA / Casbin design
notes (what they got right: default deny, explicit deny wins, policies as data, no arbitrary code), BOLA/IDOR
(OWASP API1), BFLA (API5), mass assignment (API3). Terminology note: **PBAC has no standard definition**
(vendors disagree). We define it explicitly in the docs as "named, reviewable policies evaluated by a policy
engine, each policy = effect + actions + resources + conditions" and say so. See L3.

**Design (spec).**
```
authorization:
  model: rbac | abac | pbac
  rbac:  (today's roles/permissions/row rules, unchanged)
  abac:  attributes + rules:
     subject attrs: from user columns/custom fields + role + tenant
     resource attrs: entity fields (owner, status, department, ...)
     environment attrs: allow-listed only (time window, request ip allow-list/CIDR, mfa_verified)
     rules: per (entity, op): list of conditions, each `left OP right`, left/right in
            {subject.x, resource.x, env.x, literal}; OP in eq, ne, in, not_in, lt, lte, gt, gte, is_null,
            not_null, cidr_contains. Combined all-of / any-of (max depth 3). NO expressions, NO eval.
  pbac:  policies: [{id, effect: allow|deny, actions[], resources[], conditions (same grammar as abac),
            priority}] + attachments (roles -> policies, users -> policies). Combining: deny-overrides, then
            explicit allow, else deny.
```
- Engine generated into `app/auth/policy.py` (a small, fully typed, dependency-free evaluator over data
  structures; the spec is compiled into a literal Python data module `policy_data.py`). The evaluator never
  calls `eval/exec/getattr` on user strings; attribute names are validated against an allow-list at generation
  time **and** at runtime.
- List queries: row conditions compile to SQLAlchemy `where` clauses (so listing is filtered in the database,
  not after the fact, with an explicit check on get/update/delete too). Anything that cannot be pushed down
  to SQL is rejected at generation (validation error) rather than silently post-filtered - no partial results,
  no pagination leaks.
- Field-level rules (read/write field allow-lists per role/policy) to stop mass assignment and over-exposure.
- Decision log hook: every deny emits a structured log event (feeds WP3) with policy id, never attribute values.
- Defaults: unlisted (entity, op) slot = **deny** under abac/pbac (rbac keeps its documented legacy behaviour;
  the validator warns loudly and the dashboard shows it - see L4).
- Validation: unknown attribute, type mismatch (comparing a uuid to an int), unreachable rule, deny-all policy,
  allow-all policy without conditions on a non-public entity (error unless `acknowledge_public: true`),
  policy referencing a missing role, cycles.
- **Recommender** (`app/core/authz_recommender.py`, pure function + endpoint + UI wizard): inputs = answers
  (number of roles, need for ownership/tenant rules, need for time/ip/context rules, need for per-resource
  attributes, compliance auditing needs, team size / who edits policy) or derived from the current spec;
  output = recommended model, why, what you give up, and a migration note. Deterministic scoring table, covered
  by tests, with the reasoning printed so it is auditable.

**Deliverables.** enums/spec models/validation, generator module `authz` (templates), integration with crud
templates (`_base.py` access calls), recommender, API (`/projects/{id}/authorization`, `/recommend`),
golden fixtures for each model, generated test-suite additions (a **decision-table test file generated from the
policy itself**, plus negative tests: IDOR across tenants/owners, missing attribute = deny, bad operator).
**Tests.** unit for engine (table-driven + hypothesis-style randomised cross-check against a reference
interpreter written separately in the test), generator goldens, e2e on the Docker stack for each model, SQL
push-down equivalence test (engine decision == SQL result on random rows).
**UI.** "Authorization" section (replaces "Roles & access" entry): model picker with the recommender wizard,
RBAC editor (existing), ABAC rule builder, PBAC policy list/editor, **policy simulator** ("can user U do op X on
row R?" -> decision + the matching rule, using the same evaluator through a builder-side dry-run endpoint).
**Done-when**: all three models generate, pass their generated tests in Docker, and the simulator agrees with
generated behaviour for the fixtures.

### WP3 - Observability: OpenTelemetry in generated backends (P1)
**Goal.** Optional-but-default-on `observability` section; generated app emits traces, metrics and logs over
OTLP with a ready collector, correlated and redacted.

**Research first**: OpenTelemetry Python docs (SDK, `opentelemetry-instrument` vs programmatic setup, logs
bridge status, semantic conventions for HTTP/DB, env var configuration `OTEL_*`, sampling), Collector
(receivers/processors/exporters, `memory_limiter`, `batch`, `attributes` / `redaction` processors, tail sampling),
W3C Trace Context, log-trace correlation, cardinality control, OWASP logging cheat sheet.

**Design.**
- Packages (new generated deps, section 5 D2): `opentelemetry-api`, `-sdk`, `-exporter-otlp-proto-http`,
  `-instrumentation-fastapi`, `-sqlalchemy`, `-asyncpg`, `-httpx`, `-logging` (exact set confirmed in research).
  HTTP/protobuf exporter chosen over gRPC (no grpcio compile surface, works through plain proxies).
- All behaviour from env (`OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_TRACES_SAMPLER` /
  `_ARG`, `APP_LOG_LEVEL`, `APP_OTEL_ENABLED`). **Scaling/cost changes = config only** (sample ratio, batch
  sizes, queue limits).
- Logs: structlog JSON to stdout always (12-factor) with `trace_id`/`span_id`/`request_id`/`tenant_id`;
  OTLP log export optional. **Redaction**: processor that drops/masks keys (password, token, authorization,
  secret, card, otp, ...) and a test that logs hostile payloads and asserts nothing leaks. Request/response
  bodies are never logged.
- Metrics: RED per route (rate, errors, duration histogram, route *template* not raw path to cap cardinality),
  DB pool stats, job queue depth (payments worker), authz denies, auth failures.
- Compose profile `observability`: otel-collector (+ optional Prometheus/Grafana/Tempo or Jaeger via profile),
  `otel-collector.yaml` with memory_limiter, batch, redaction, tail-sampling stanza commented with sizing notes.
- Health: `/healthz` (liveness), `/readyz` (db + dependencies) kept free of tracing noise (excluded urls).
- Builder itself also gets the same setup behind env (dogfooding), off by default.
**Tests.** unit (redaction, sampler config), generated-project e2e: run the stack with a collector that writes to
file, hit endpoints, assert spans/log correlation/metric names exist and that secrets are absent.
**UI.** "Observability" section: enable, endpoint, sampling %, retention hints, what is collected, redaction list
(add-only), generated dashboards list; sizing hint from expected RPS.

### WP4 - CI/CD and cloud deployment for AWS, Azure, GCP (P1)
**Goal.** From a project, generate a secure, reviewable delivery path: pipeline + infrastructure-as-code +
runtime config for a chosen cloud, driven by a small configuration (size, region, environments), secrets never
held by the builder.

**Research first**: GitHub Actions OIDC federation for AWS / Azure / GCP (official docs of each), Terraform
provider auth via OIDC, minimal-privilege roles, private networking patterns (AWS ECS Fargate + RDS in private
subnets + ALB/WAF, Azure Container Apps + Flexible Server with private access, GCP Cloud Run + Cloud SQL private
IP + Serverless VPC connector / Direct VPC egress), secrets managers, container scanning (Trivy), SBOM, image
signing (cosign keyless), SLSA basics, migration step in pipeline, rollback strategy.

**Design.**
- Order: **CI first** (lint, type-check, tests, build, scan, SBOM), then **CD** (build once, push, migrate, deploy,
  smoke test, auto-rollback on failed health). Provider CI: GitHub Actions first; GitLab CI listed as follow-up (L6).
- IaC: Terraform (HCL) modules per cloud under `deploy/<cloud>/` with `environments/{dev,staging,prod}.tfvars`.
  Scaling is **tfvars only** (min/max instances, cpu/memory, db tier, storage, HA on/off), computed from the
  same sizing notion as `payments_sizing.py` and shown in the dashboard.
- Security by default: private DB (no public IP), TLS everywhere, secrets from the cloud secret manager injected as
  env (never in tfvars/state output marked sensitive), encrypted storage, least-privilege task roles, WAF/rate
  limit where the cloud offers it cheaply, deletion protection + backups in prod, remote state with locking
  (S3+DynamoDB/ Azure Storage / GCS) described and bootstrapped by a one-time `bootstrap/` module.
- **No cloud credentials in the builder.** Pipelines authenticate by OIDC workload identity; the dashboard shows
  the exact one-time trust setup (role/identity/pool creation snippet) and a verification checklist.
- Platform side: `deployment_targets` records (cloud, region, environments, repo, status of a checklist), no
  credentials; "Deploy" area with per-environment cards, pipeline status links, drift/health notes.
- A follow-up (L7): letting the platform *itself* run `terraform apply` with customer cloud access. Deliberately
  not built: highest-blast-radius feature, needs its own threat model.
**Tests.** generator goldens; `terraform fmt -check` + `terraform validate` per cloud inside a hashicorp container
(offline, with providers cached once); `actionlint`-style YAML schema checks; a test that no secret-looking
literal appears; policy tests (tfsec/trivy config scan in container if the image can be pulled).
**UI.** "Deploy" group: cloud picker, environments, sizing sliders -> live tfvars preview, trust-setup wizard,
checklist, downloadable bundle.
Real-cloud `apply` is **unverified** (no credentials in this run); stated in section 6.

### WP5 - PDF documents (billing and beyond) (P2)
**Goal.** `documents` feature: generated projects can render PDFs (invoice, receipt, statement, quote, purchase
order, packing slip, certificate, report, contract/letter, ID/ticket) from data, with 10 built-in templates and
user-defined bodies.

**Research first**: which industries/apps use document generation most and why now (e-invoicing mandates:
EU ViDA/Peppol, India GST e-invoice, Italy SDI, Germany ZUGFeRD/XRechnung 2025 receiving obligation; SaaS
billing, marketplaces, logistics, healthcare reports, HR/payroll, education certificates), PDF/A and PDF/A-3
for archival and embedded XML invoices, accessibility (tagged PDF), engines compared (ReportLab, fpdf2,
WeasyPrint, headless Chromium), font licensing and Unicode/RTL/Indic shaping, security (SSTI, SSRF through
HTML, zip/PDF bombs, memory), performance (render in worker, cache by content hash).

**Design.**
- Engine choice recorded after research (section 5 D3). Working assumption: **ReportLab** (no system libs, pure
  pip, deterministic, no network access, no HTML engine = no SSRF/local-file-read surface), templates are
  declarative JSON/YAML layout trees, not code. HTML->PDF (WeasyPrint) is a documented option requiring native
  libs and URL-fetch lockdown; rejected as default for supply-chain and SSRF reasons.
- User-defined body = **structured blocks** (heading, paragraph, key-value table, line-items table, totals,
  image from storage/file field, page break, signature line, QR/barcode) with `{{ path.to.value }}`
  placeholders resolved by a **tiny safe resolver** (dotted lookup, a short allow-list of formatters:
  money, date, upper, lower, default). Not Jinja at runtime, so no code execution path. Placeholders validated
  against the entity fields at generation time.
- Templates ship as data (`documents/templates/*.json`) and render through the same path, so "customise a
  built-in" = copy and edit.
- Money uses the existing `currencies.py` minor-unit logic. Tax lines explicit; totals recomputed server-side,
  never trusted from input. Document numbering via a DB sequence per tenant/series (gapless is a legal
  requirement in some countries -> documented, `FOR UPDATE` row counter).
- Endpoints: `POST /documents/{template}/render` (returns PDF), stored-document option via the storage feature
  with hash + retention; async render for big jobs via the existing job-queue pattern; access control through the
  WP2 engine (a document is just a resource).
- Limits: max pages, max items, max image bytes, render timeout, per-user rate limit.
**Tests.** golden *layout trees* (PDF bytes are not byte-stable across library versions; we assert extracted text
and page count with a PDF text extractor in test only, plus deterministic metadata), hostile placeholder tests,
limits, template validation, e2e render in the Docker stack.
**UI.** "Documents" section: template gallery with thumbnails (rendered from sample data at build time), block
editor, placeholder picker from the entity fields, live preview via the dry-run endpoint, bind to entity/event.

### WP6 - Builder as an MCP server (Lovable and other MCP clients) (P2)
**Goal.** The platform exposes an MCP endpoint so Lovable (or Claude, Cursor, ...) can read and, with consent,
modify a project: understand the generated API and build a dashboard/frontend against it.

**Research first**: MCP spec (current revision: transports, authorization = OAuth 2.1 resource server, RFC 9728
protected-resource metadata, RFC 8414, dynamic client registration RFC 7591), official Python SDK
(`mcp` package, FastMCP, `streamable_http_app`, `TokenVerifier`), Lovable's custom MCP behaviour (L1),
tool-poisoning / prompt-injection risks for MCP servers (treat all tool *outputs* as untrusted by the client; our
outputs contain user-authored names/descriptions), least-privilege tool scopes.

**Design.**
- Mounted in the same app at `/mcp` (streamable HTTP). **Auth**: Bearer PAT from WP1 with scopes
  (`mcp:read`, `mcp:write`, `mcp:generate`); OAuth 2.1 (what Lovable uses by default) is the follow-up (L2) and the
  protected-resource metadata endpoint is added now so clients can discover that PATs are accepted.
- Tools (all project-scoped by the token owner's membership, every call audited):
  read: `list_projects`, `get_project_spec`, `get_data_model`, `get_openapi` (of the *generated* API),
  `get_auth_model`, `get_frontend_contract` (typed client snippet + auth flow + error shapes + pagination
  conventions so a UI builder can wire a dashboard correctly), `get_deploy_info`, `validate_spec`;
  write (scope `mcp:write`, confirmation-style names, size-limited): `create_entity`, `add_field`,
  `add_relation`, `set_permissions`; `generate_project` returns a download link (scope `mcp:generate`), never
  inline secrets. Destructive ops (delete) are **not exposed**.
- Resources: `spec://{project}`, `openapi://{project}`; prompts: "build an admin dashboard for project X".
- Output hygiene: never return secrets, tokens, internal ids beyond need; cap response sizes; strip control chars.
**Tests.** MCP client (SDK's in-process client) against the app: scope enforcement, cross-user isolation,
schema of every tool, injection-ish names, oversize.
**UI.** "Integrations" page: create scoped token, copy connector config for Lovable / Claude / Cursor, usage log
(from audit), revoke.

### WP7 - Dashboard information architecture (P2, started in WP1, closed here)
Research: grouped-nav patterns for dense admin products (Stripe, Vercel, Supabase, Railway, AWS console pitfalls),
progressive disclosure, status-first overview, deep-linkable tabs, command palette, empty-state design.
Design: top bar (org/account, global search/command palette, help, status), **left rail groups**:
`Build` (Overview, Data model, Documents) / `Security` (Authentication, Keycloak, Authorization, Secrets) /
`Features` (Payments, File uploads) / `Operate` (Observability, Deploy, Environments) / `Ship` (Generate,
Integrations/MCP, Docs). Each group page = overview cards + tabs inside (e.g. Deploy: Targets / Pipeline / Sizing /
Checklist). Project **Overview becomes a readiness board** (what is on, what is unfinished, what is risky).
Routing stays hash-based and deep-linkable (`#/p/<id>/<group>/<tab>`). Admin console has its own shell.
Done-when: no section needs horizontal sidebar scrolling at 1366x768, every feature reachable in <= 2 clicks.

### WP8 - Documentation (P3)
- **Generated project docs** (generated, always current with the spec): `docs/` with architecture overview, data
  model + ER diagram (mermaid), **authorization matrix rendered from the policy** (who can do what), auth flows,
  configuration reference (every env var, default, security note, scaling effect), deployment runbook per cloud,
  observability guide, PDF template guide, security notes + known limitations, ADRs for choices made.
- **Platform docs**: `docs/` in the repo (getting started, concepts, spec reference generated from pydantic
  schemas, API reference link to OpenAPI, admin guide, MCP guide, security model), plus in-dashboard contextual
  help ("?" drawers) reusing the same markdown.
- Rule: docs are generated from code/spec where possible, so they cannot drift; a test fails if an env var or
  spec field exists without a doc entry.

### WP9 - Cross-cutting, continuous
- Limitations register (section 6) updated live. Security self-review at the end of each package with the
  checklist in section 3. Final pass: full test suites, ruff, mypy, frontend tsc/build, a summary at the top of
  this file for the owner.
- Config-only scalability audit: list every knob a user needs to scale (workers, pool size, rate limits,
  cache TTLs, sample rates, instance sizes) and confirm each is an env var or tfvars, none a code change.

## 3. The "second look" checklist (AI-miss guard, run at the end of every package)

Things that look wrong but are fine and things that look fine but are wrong - check both:
1. Re-read the diff as an attacker: what input did I assume valid? Missing authz on a new route? Object id taken
   from the client without ownership check? Anything logged that could be sensitive? Error text leaking internals?
2. Look for the default: what happens if the new config is absent / empty / wrong type? Must fail closed.
3. Run the thing for real (Docker), do not trust unit tests alone; try one hostile request by hand.
4. Compare against the docs I researched, not memory: names of env vars, flags, library calls (versions drift).
5. Re-run earlier packages' tests (regressions), including goldens (`tests/golden` diffs must be intended).
6. Odd-but-normal vs normal-looking-but-wrong: explain every golden diff line; check generated code compiles
   (`python -m compileall`), passes ruff/mypy where the generated project enforces them.
7. Cost/abuse: unbounded list, upload, render, retry, loop, fan-out? Add a limit and a test.
8. Does it need a migration for existing data? Is the migration reversible and safe on a populated DB?
9. UI: does the feature exist in the dashboard, with empty/loading/error states, and is it reachable?
10. Is a new limitation or deviation recorded in section 6 and in the package's notes?

## 4. Status board (update after every package)

| WP | Package | Status | Notes |
|---|---|---|---|
| 0 | Baseline + hygiene | [x] | 2026-10-24: unit+api 1009 passed, 3 failed = stale `storage_*` goldens (storage test templates gained assertions after the goldens were written; diff reviewed, intended) -> regenerated. e2e (Docker stack) not part of baseline. |
| 1 | Platform auth, IAM, admin/customer split | [x] | 2026-10-24. Built and verified (details in section 7). Unit + API: 1153+ tests green; migration tested on real Postgres incl. upgrade over 8 existing projects; live curl smoke test and browser check of login, session resume, account page, Share dialog and admin console. Open follow-ups: L9-L12. |
| 2 | RBAC / ABAC / PBAC + recommender | [x] | 2026-10-24. Engine, generator, builder persistence (`project_authorizations`, migration `f6b2d84a1c35`), API (get/put/issues/simulate/coverage/recommend), recommender, dashboard "Authorization" section (verified in the browser), e2e on real Postgres for abac, pbac and pbac + multi-tenant + soft delete + many-to-many; generated-code goldens also for Keycloak (shared and tenant). Unit + API 1328 tests green. Limitations L15-L20 below. |
| 3 | OpenTelemetry observability | [x] | 2026-10-24. Spec block + validation, persistence (`project_observability`, migration `a8d4f1c7b362`), API, generator feature (telemetry module, redacting exporter, trace-correlated logs, counters, tests, docs, compose overlay with collector/Jaeger/Prometheus), dashboard Observability section (verified in the browser). Verified for real: generated telemetry tests in Docker/Postgres (`obs_blog`, `obs_vault`); the generated collector config validates in the pinned collector image; real OTLP from a generated service through a real collector arrives with route templates and no secrets (`tests/e2e/test_observability_stack.py`). Not done: builder dogfooding, OTLP log export (L23-L29). |
| 4 | CI/CD + AWS/Azure/GCP | [x] | 2026-10-24. Spec block + validation + sizing profiles, persistence (`project_deployments`, migration `b9e5a2d8c473`), API (get/put/issues/plan), generator feature (CI, per-cloud deploy workflow, dependabot, Terraform stack + bootstrap for aws/azure/gcp, tfvars from sizing, DEPLOYMENT.md), dashboard Deploy section (verified in the browser). Verified for real in Docker: `terraform fmt`/`init`/`validate` of all six roots against the real providers (aws 6.70, azurerm 5.11, google 8.8), `actionlint` on the three deploy workflows, no-secret and SHA-pin scans (`tests/e2e/test_deploy_bundles.py`). **Not done / unverified:** `terraform apply` in a real account (L30), platform-side deployment tracking (L37). |
| 5 | PDF documents | [ ] | |
| 6 | MCP server | [ ] | |
| 7 | Dashboard IA | [ ] | |
| 8 | Documentation | [ ] | |
| 9 | Final audit | [ ] | |

Realistic expectation for 5-8 hours: WP0-WP3 complete with depth, WP4 generation + validation, WP5-WP6 as far
as time allows; anything not started is described in its section so the next run can begin immediately.

## 5. Decisions taken on the owner's behalf (veto any of these)

- **D1 Platform auth is built in-house** (scrypt, HS256 JWT, rotating refresh), not Keycloak: the builder must run
  with zero extra services, and it mirrors the audited generated-auth primitives. Keycloak stays the option for
  *generated* projects. Revisit if you want SSO for the platform itself (L8).
- **D2 OpenTelemetry packages** added to generated projects that enable observability (OTLP/HTTP exporter).
- **D3 PDF engine = ReportLab** (BSD) in generated projects that enable documents; declarative block templates,
  no HTML/Jinja at render time. (Alternative recorded: WeasyPrint, needs system libs.)
- **D4 MCP SDK = official `mcp` package** in the builder only (not in generated projects).
- **D5 Terraform** for IaC, GitHub Actions first for CI/CD.
- **D6 Existing projects are assigned to the bootstrap admin** on migration; no data is deleted.
- **D7 Uncommitted work stays uncommitted.** I will not commit or push.

## 6. Limitations and risks register (item 9 of the brief: live, newest at the bottom)

| ID | Sev | Found in | Statement | Impact / plan |
|---|---|---|---|---|
| L0 | critical | audit | Builder API had no authentication or project ownership. | Fixed first in WP1; until then do not expose the builder beyond localhost. |
| L1 | high | WP6 research | Lovable "custom MCP" is a **personal chat connector** that provides live *context* in Lovable chats; it is not part of the published app and connections are per-user. Docs do not state transport or OAuth details (DCR/PKCE/redirects). | We can feed Lovable the data model, OpenAPI, auth flow and a typed client contract so it builds the dashboard correctly; "Lovable creates things in our platform" depends on Lovable honouring write tools, **unverified**. Design is read-first. Needs a manual test by the owner in Lovable. |
| L2 | medium | WP6 research | Lovable defaults to OAuth for custom MCP; PAT/bearer is supported as the alternative. A full OAuth 2.1 authorization server (DCR, PKCE) in the builder is a sizeable security surface. | v1 uses bearer PAT; OAuth AS is a follow-up package with its own threat model. |
| L3 | medium | WP2 research | "PBAC" has no standard definition; vendors contradict each other. | We define it explicitly in product and docs; the label is ours, ABAC semantics follow NIST SP 800-162. |
| L4 | medium | WP2 design | Under RBAC, unlisted (entity, op) slots are **public** (documented earlier decision); that is surprising and dangerous. | ABAC/PBAC default-deny; RBAC keeps behaviour for compatibility but validator + dashboard warn; consider flipping the default in a spec version bump (needs owner decision). |
| L5 | low | WP1 design | No breached-password (HIBP) check, no MFA for platform accounts, in-process rate limiting is per worker. | Follow-ups; documented; MFA for admin accounts is the first one to schedule. |
| L6 | low | WP4 design | Only GitHub Actions generated (GitLab/Bitbucket later). | |
| L7 | high | WP4 design | Platform-run `terraform apply` with customer cloud access is not built. Real-cloud deploys cannot be verified without credentials; only `validate`/`plan`-level checks run here. | Marked unverified; first real deploy should be done by the owner in a throwaway account. |
| L8 | low | D1 | Platform SSO (Google/Microsoft) is not included. | Follow-up. |
| L9 | high | WP1 | The builder has **no e-mail sender**, so there is no e-mail verification and no e-mailed password reset. Anyone can sign up with an address they do not own, and a forgotten password needs an administrator (`/admin` -> Reset password). Because project members are added **by e-mail address**, someone could register `victim@corp.com` first and be granted access meant for the real person. | Run production with `BUILDER_SIGNUP_MODE=closed` (administrators create accounts) until verification exists. Follow-up package "WP1b": SMTP settings for the platform, verification link, reset link, same `delivery` pattern as generated projects. |
| L10 | medium | WP1 | `POST /account/register` (409) and adding a member (404) reveal whether an e-mail has an account. Login and admin errors do not. | Rate limited; inherent without e-mail verification. Resolved by WP1b (always answer "check your e-mail"). |
| L11 | medium | WP1 | The audit log's append-only trigger stops the application, not a database superuser. Oversized *chunked* request bodies are cut off, not answered with a clean 413 (Content-Length bodies get 413). | Ship the audit log to external storage (WP3 observability) for real tamper evidence. |
| L12 | high | WP1 | docker-compose is a **development** setup (Vite dev server, `--reload`, bind mounts, a dev `SECRET_KEY` default that the app refuses outside `local`). The builder platform itself has no production packaging yet (static dashboard behind TLS, CSP headers on the dashboard host, non-reload image). The access token lives in JS memory, so a script-injection bug in the dashboard could use it for the page's lifetime. | Package the platform for production (WP4 covers generated projects, not the builder itself); serve the built dashboard with a strict CSP. Do not expose the dev compose setup to the internet. |
| L13 | low | WP1 | No MFA for platform accounts (administrators included), no breached-password check, no per-device session list. | Schedule MFA for the admin console first. |
| L14 | info | WP0 | Before this run the repository held uncommitted storage work whose golden fixtures were stale (3 tests red). Regenerated after reading the diff (only added assertions in generated tests). | Review `git diff tests/golden` before committing. |
| L15 | medium | WP2 | No public (signed-out) routes under abac/pbac; use rbac for those (validation says so). | |
| L16 | medium | WP2 | Deny policies whose condition looks at an empty field do not fire (missing never matches). | Documented in the generated docs; consider a validation warning for deny conditions on optional fields. |
| L17 | medium | WP2 | Resource attributes are an entity's own fields plus id/created_at/updated_at/created_by_id; conditions on a parent record's attributes are not expressible. | Follow-up. |
| L18 | low | WP2 | Update re-check is "must still be readable" (the `get` policy), not "must satisfy update again"; create is checked against the payload, so omitted fields are None. | |
| L19 | low | WP2 | `client_ip` is `request.client.host`; behind a proxy run uvicorn with `--proxy-headers --forwarded-allow-ips`. | Documented in generated docs. |
| L20 | info | WP2 | Field-level (write allow-list) rules are not part of v1. | |
| L21 | low | WP2 | The recommender is a hand-set scoring table (weights are judgement, not data). | Reasons are printed so a human can overrule it. |
| L22 | low | WP2 | Switching a project back to rbac in the dashboard deletes its policies (confirmed first). Keycloak-provider ABAC/PBAC is verified at generation + generated-test level, not against a live Keycloak. | |
| L23 | medium | WP3 | Logs are not exported over OTLP; they stay JSON on stdout and carry `trace_id`. | Ship stdout with the platform's log collector. The Python logs SDK is the least settled part of OTel; revisit later. |
| L24 | medium | WP3 | `opentelemetry-instrumentation-sqlalchemy` 0.66b1 refuses SQLAlchemy 2.1 ("nothing can be instrumented", found by the generated test). DB spans therefore come from the **asyncpg** instrumentation (statement text with `$1` placeholders, no values, no ORM-level names). | Switch back when the SQLAlchemy instrumentation supports 2.1. |
| L25 | low | WP3 | Only the web process is instrumented; the payments worker and other background processes are not. | Follow-up. |
| L26 | low | WP3 | Deviation from the plan's "default-on": observability is **off until saved** (a project without the block generates exactly the same bytes as before). | Dashboard enables it per project; new-project default can flip later. |
| L27 | low | WP3 | The builder itself is not instrumented (dogfooding deferred). | Follow-up. |
| L28 | medium | WP3 | Only the local stack (collector, Jaeger, Prometheus) was exercised. Hosted backends (Datadog, Grafana Cloud, Honeycomb...) and the commented tail-sampling stanza are untested. | **Unverified**; first real backend should be checked by the owner. |
| L29 | low | WP3 | OTel instrumentation packages are beta (`0.x`b); generated projects pin `>=0.66b1,<0.67`. `tenant_id` is not attached to spans or logs. | Review on each OTel release. |
| L30 | high | WP4 | `terraform apply` and the pipelines were **never run against a real AWS, Azure or Google Cloud account** (no credentials in this run). Only `terraform validate` (real provider schemas) and `actionlint` passed. Runtime errors (quotas, naming collisions, IAM propagation, `?ssl=require` against the managed PostgreSQL with asyncpg) are possible. | The owner should run the first deployment in a throwaway account / the dev environment. |
| L31 | medium | WP4 | Specs using payments (worker), file storage (malware scanner, object store), Redis token storage or a Keycloak server of their own cannot enable deployment: validation refuses them. | Follow-ups per feature; silently dropping a worker would be worse. |
| L32 | medium | WP4 | The deploy identities created by `bootstrap/` are powerful inside their account/project/subscription (network, database, role management). No permissions boundary. | Documented; use one account per environment for production. |
| L33 | low | WP4 | The generated database password is in the Terraform state as well as the secret manager. | State storage is private, versioned and encrypted; limit who reads it. Managed-password options (RDS managed secret, IAM auth) are a follow-up. |
| L34 | low | WP4 | Azure: Key Vault cannot hold an empty secret, so Terraform writes a placeholder and the pipeline refuses to deploy while one remains. | By design. |
| L35 | low | WP4 | No WAF on Azure and Google Cloud (needs Front Door / Cloud Armor plus a load balancer); AWS WAF uses AWS managed rules and a rate limit with default settings. | Documented in DEPLOYMENT.md. |
| L36 | low | WP4 | GitHub Action SHAs and image tags were looked up on 2026-10-24 and will age; dependabot.yml is generated to propose updates. Images are built for amd64 only. | |
| L37 | medium | WP4 | The plan's platform-side `deployment_targets` records (checklist status, pipeline links, drift notes) are not built: the Deploy section edits the spec block and shows the setup steps only. | Follow-up. |
| L38 | low | WP4 | The pipeline uses `terraform apply -target` once per deployment to register the migration task/job with the new image before the service moves (Terraform warns about targeted applies; this use is intentional). | |

## 7. Package notes

### WP1 - what was built (2026-10-24)
- `app/core/platform_security.py` (scrypt N=2^15, pinned-alg HS256 JWT, opaque rotating refresh tokens, `bb_pat_` API tokens, HKDF-separated signing key), `platform_authz.py` (permission tables as data), `ratelimit.py`.
- Tables `platform_users`, `platform_refresh_tokens`, `platform_api_tokens`, `project_members`, `platform_audit_log` (migration `e5a1c93b7d42`, audit append-only trigger, lower-case e-mail check constraint).
- `app/api/security.py`: one guard attached to **every** builder router in `app/main.py`; resolves the owning project of any route from its path (project id or child resource id), 404 for non-members, role by method, API-token scopes, `must_change_password` block, audited denials and audited successful changes. Fails closed for routes that name no project.
- `/account/*` (customers), `/admin/*` (staff; different JWT audience, cookie, session length), `/projects/{id}/members`.
- Hardening in `app/main.py`: security headers + CSP + HSTS (non-local), request ids, 10 MiB body cap, credentialed CORS with explicit origins only, startup refuses weak/placeholder `SECRET_KEY` outside `local`, docs hidden outside `local`.
- Tests: `tests/unit/test_platform_security.py` (66), `tests/api/test_account.py`, `test_access_matrix.py` (route walk + unauthenticated sweep + IDOR sweep + role matrix), `test_admin.py`, `test_migrations.py` (real Alembic chain). Mutation check: breaking the membership check, the role check or the audience check each fails a test.
- UI: sign-in/sign-up, session resume from cookie, Account page (password, API tokens shown once, sign out everywhere), Share dialog (members), admin console (overview, people, projects, audit log, settings) with its own shell and sign-in. Seed script, Postman collection, compose, `.env.example`, README updated.
- Operations: `scripts/create_admin.py` (`--adopt-projects` claims pre-accounts projects). On this machine's Docker volume the 8 demo projects were adopted by `admin@example.com` (local test admin created during verification; its password is in this run's transcript only, **change or delete it**).

## 8. CHECKPOINT (written 2026-10-24, end of the first session)

**Resume here.** WP1-WP4 are finished; continue with WP5 (PDF documents), section 2.

### Verified state of the tree
- `uv run pytest tests/unit tests/api`: all green after the last fixes (1296 tests; two `test_generated_auth` expectations updated for the new `policy` key). `uv run mypy app` clean. `ruff` clean on new code (older files keep pre-existing E501s).
- e2e (Docker): `tests/e2e/test_compose_stack.py` passed (WP1 fixture change); `tests/e2e/test_authz_stack.py` passed for both models on a real Postgres. Not re-run since the final lint-only edits: run `uv run pytest tests/e2e/test_authz_stack.py -q` first.
- Nothing is committed. The working tree also contains earlier uncommitted storage work.
- Docker: the dev stack (postgres volume with 8 demo projects adopted by test admin `admin@example.com`) was started by me and may still be running (`docker compose stop` to stop). **Change/delete that test admin.**

### WP1 (done): see section 7.

### WP2 done so far
- `app/core/authz_engine.py`: the policy engine (single source of truth; copied byte-for-byte into generated projects as `app/auth/policy.py`). Default deny, deny overrides, JSON conditions only (no eval), SQL pushdown + Python re-check, two-valued leaves (no NULL surprises). `tests/unit/test_authz_engine.py` (68 tests incl. a 500-case random three-way check: SQL == Python == independent reference; three deliberate engine breaks were each caught).
- Spec: `SpecPolicy`, `SpecAuthorization`, `Spec.authorization`, enum `AuthorizationModel`. Validation: `app/core/validation_authorization.py` (hooked into `validate`), `tests/unit/test_authz_validation.py` (61 tests).
- Generator: `features/authz/` (`module.py`, `describe.py`, templates `authorize.py.tpl`, `tests/test_authz.py.j2`, `docs/AUTHORIZATION.md.j2`), registered in `engine.py`; `context.py` (`AccessCtx.policy`, `EntityCtx.policy`, `_attach_policy_access`: every op needs sign-in; multi-tenant projects are auto tenant-scoped; `created_by_id` only when a policy mentions it); router template, `access.py.tpl` (`Access.policy`), repository `_base.py.tpl` (row filter on every query, create/update write checks, post-write re-read without the op's own filter - a real bug found by the e2e run), tests module (no generic smoke test for policy entities).
- Fixtures `tests/fixtures/specs/authz_abac.json` (Tickets) and `authz_pbac.json` (Docs); scenario tests `tests/e2e/authz_scenarios/*.py`; goldens regenerated (only `_base.py` in 18 and `access.py` in 15 existing projects changed, plus new `authz_*` goldens).
- Also fixed a pre-existing generator bug found by the new fixtures: `delivery.py` imported `asyncio`/`config` unused when neither SMTP nor SMS is configured.

### WP2: finished (see status board). Nothing remains except the optional follow-ups in L15-L22.

### After WP2 (unchanged order): WP3 OpenTelemetry, WP4 CI/CD + clouds, WP5 PDF documents, WP6 MCP, WP7 dashboard IA, WP8 docs, WP9 final audit. Decisions already taken are in section 5 (veto-able).

### Recipes / gotchas
- Write patch scripts with the Write tool (scratchpad) and run them; Bash heredocs containing apostrophes break the whole command.
- API tests: `client` fixture = signed-in customer; `client_for("x@y.z")`, `anon_client`, `make_user`; admin audience via `client_for(..., audience=sec.AUDIENCE_ADMIN)`.
- Goldens: `UPDATE_GOLDEN=1 uv run pytest tests/unit/test_generator.py` then review `git diff tests/golden`.
- Frontend check without Node: see memory note (docker node:22-alpine, `npx tsc -b && npx vite build`, delete `dist`). `#root` is an Oat sidebar grid: full-page screens need `grid-column: 1 / -1`; admin shell must keep nav/aside/main as direct children of `#root`.

