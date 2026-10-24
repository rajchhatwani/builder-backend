# Backend Builder

Internal FastAPI service that turns a structured spec (entities, fields, relations,
endpoint options) into a complete, runnable FastAPI project you download as a zip.
See `VISION.md` for the long-term product and `PLAN.md` for the Phase 1 build plan.

**Status: M5 (end-to-end proof) written; Phase 1 feature-complete pending a green e2e run.**
Define a data model through the API (or the UI in `frontend/`), validate it, and download a
runnable FastAPI project as a zip:

- Builder CRUD for projects, entities, fields, relations; `GET/PUT /projects/{id}/spec`;
  `POST /projects/{id}/validate`.
- `POST /projects/{id}/generate/preview`, `GET /projects/{id}/generate/download` (zip, recorded),
  `GET /projects/{id}/generations`, `GET /generations/{id}`.
- Postman collection: `postman/backend-builder.postman_collection.json` (start with the
  "Blog demo" folder and run it in order).
- UI: `cd frontend && npm install && npm run dev` (talks to `http://localhost:8000`). Open an
  entity to edit fields and API options; the project page validates, previews and downloads.

The generator is the pure function `app.core.generator.generate(spec)`. Regenerate golden
files after a deliberate template change with
`UPDATE_GOLDEN=1 uv run python -m pytest tests/unit/test_generator.py -k golden`.

### Authentication (Phase 2)

Add an `auth` block to a project and the generated backend gains sign-up, sign-in and the
email / mobile flows, in `app/auth/` with its own migration (`0002_auth.py`) and tests.

- Configure over the API: `POST/GET/PATCH /projects/{id}/auth` (tokens, SMTP, SMS provider,
  rate limits, branding), `PUT /projects/{id}/auth/secrets` (SMTP / SMS credentials, encrypted
  at rest with `SECRET_KEY`, never returned), `/projects/{id}/roles`,
  `/projects/{id}/auth/custom-fields` (become real columns on `auth_users`) and
  `/projects/{id}/permissions`. The block is part of `GET/PUT /projects/{id}/spec`.
- Generated routes under `/auth`: register, login, refresh (rotating, reuse-detecting),
  logout, me, change password, delete account; email verification and magic-link sign-in
  (SMTP); phone verification, SMS-code sign-in and password reset by email link or SMS code
  (Twilio, Vonage or AWS SNS). Protect your own routes with `CurrentUser` and
  `require_roles(...)` from `app/auth/deps.py`.
- **Permissions are enforced on the generated CRUD routes.** Each `(entity, operation)` slot
  lists the roles that may call it (empty = public) and an optional row rule: `owner` (only
  rows the caller created), `role_scoped` (like `owner`, but the `admin` role sees every row)
  or `custom_filter` (only rows where a string / enum / integer / boolean field equals a
  value). Owned entities get a `created_by_id` column (added by `0002_auth.py`) and stamp it on
  create. Slots without a permission stay public, and a permission on a disabled operation has
  no effect. Unauthorised callers get 401, wrong-role callers 403, and rows outside the
  caller's scope are reported as 404.
- **Multi-tenancy** (`multi_tenant`). Rows of different tenants never mix. Signing up without
  an invitation creates a tenant (`tenant_name` in the register body) and makes the user its
  `admin`; admins invite people into their own tenant, and an invitation joins exactly that
  tenant. `GET /auth/tenant` returns the caller's tenant and access tokens carry a `tid` claim.
  One `tenant` row rule on any operation of an entity puts the whole entity inside the tenant:
  it gets a `tenant_id` column, every operation is limited to the caller's tenant, new rows are
  stamped with it, and a signed-in user is required. This uses a shared schema (one set of
  tables with a `tenant_id` column), which suits most SaaS apps; it cannot be combined with
  invite-only sign-up, since nobody could then create the first tenant.
- **Invitations and role flags.** With `registration.invite_only` (or any role marked
  `invite_only`) admins use `POST/GET/DELETE /auth/invitations` to email a one-time
  registration link bound to one address (it also verifies that address and can grant roles).
  Roles marked `self_assignable` can be picked in the register body.
- Dependencies stay small: password hashing (scrypt), HS256 JWT, SMTP and the Twilio/Vonage
  calls use the standard library. Options add a package only when selected: `cryptography`
  for `RS256` (tokens verifiable with the public key at `/auth/jwks.json`), `redis` for
  `token_store: redis` (refresh tokens in Redis, with a Redis service in the compose file),
  `boto3` for `aws_sns`.
- Credentials are **not** written into the generated source or the zip. The project reads them
  from `AUTH_JWT_SECRET` (or `AUTH_JWT_PRIVATE_KEY`), `SMTP_*`, `TWILIO_*` / `VONAGE_*` / `AWS_*`
  in its environment (see its `.env.example`); the dashboard lists them after a download.
  `python3 -m app.auth.keys` inside the generated project prints a fresh signing secret.
  Credentials stored with `PUT /projects/{id}/auth/secrets` stay on the builder and are not
  used by generation (see "Not yet").

### Keycloak (single sign-on)

A project can use **Keycloak** instead of the built-in auth. The generated backend then issues no
tokens of its own: it only verifies Keycloak access tokens and applies your roles, permissions and
row rules, so sign-in, passwords, MFA, social login and user management live in Keycloak. The full
design, decisions and verification notes are in `KEYCLOAK_PLAN.md`.

- Configure over the API: `PUT/GET /projects/{id}/keycloak` (realm, client ids, redirect URLs,
  password / MFA / session / audit settings, identity providers), `GET .../keycloak/impact?action=`
  and `POST .../keycloak/enable|disable` with `{"confirm": true}`. The settings are part of
  `GET/PUT .../spec` (`auth.provider`, `auth.keycloak`). Client **secrets are never stored**: each
  login's secret is an environment variable (`KC_IDP_<ALIAS>_CLIENT_SECRET`) of the generated project.
- Two modes: `own` (the zip starts Keycloak with its own Postgres and an imported realm: hardened
  defaults, your roles as client roles, Google / Microsoft Entra ID / GitHub / generic OIDC logins,
  a Swagger UI sign-in client) and `shared` (no Keycloak in the zip; `scripts/keycloak_register.py`
  adds this project's clients and roles to an existing realm, so one login works across projects).
  Roles are client roles of each project's API client, and each API accepts only tokens issued for
  its own client, so projects sharing a realm never accept each other's tokens.
- Turning it off is deliberate: it needs `confirm`, reports its impact first, is refused while
  another project still uses this project's realm, and keeps the settings so it can be turned back
  on. The generated app records the provider it first started with and refuses to boot on a database
  used by another one unless `AUTH_ALLOW_PROVIDER_SWITCH=true` (this lock exists for built-in auth too).
- **Multi-tenancy** works through Keycloak Organizations: each organization is a tenant (ids derived from
  the alias), a user must be in exactly one, and the `tenant` row rule behaves as with built-in auth.
  **Custom registration fields** become Keycloak user-profile attributes (with validators per type) delivered
  as token claims and copied to `auth_users`. Keycloak cannot keep a value unique, so `unique` is rejected.
- Not available with Keycloak (rejected by validation, never silently ignored): SMS codes, self-assignable
  and invite-only roles.
- Verified against a real Keycloak: `uv run pytest tests/e2e/test_keycloak_stack.py` (needs Docker,
  pulls the pinned Keycloak image, a few minutes).

### Payments

A project can take **card payments** through a provider's hosted checkout (Stripe Checkout or Razorpay Payment
Links). The generated backend gets a payment module, a **separately deployable worker**, and deployment files
sized for the traffic you expect. Design, decisions, phases and the verified / unverified list are in
`PAYMENTS_PLAN.md`.

- Configure over the API: `PUT/GET /projects/{id}/payments` (provider, the entity that is paid for and its amount /
  currency / status fields, currencies, return addresses, roles, refund-approval limit, expected load, security
  knobs), `GET .../payments/sizing` (replicas, workers and database connections for the load: an estimate),
  `GET .../payments/impact?action=` and `POST .../payments/enable|disable` with `{"confirm": true}`. The settings are
  part of `GET/PUT .../spec` (`payments`). **No provider key or webhook secret is stored anywhere in the builder or put
  in the zip**: they are environment variables of the generated project (`STRIPE_*` / `RAZORPAY_*`, or `*_FILE`).
- Generated routes: `POST /payments` (needs an `Idempotency-Key`; the amount is read from your own row on the
  server, never from the request), `GET /payments`, cancel, refunds (with an optional second approver above a limit),
  disputes, `/payments/ops/*` (queue health, failed jobs, audit-chain check) and the signature-checked webhook.
- Safe by construction: card data never reaches the code; a webhook is only a hint (the object is fetched from the
  provider before anything changes); every state change is a guarded atomic update; one live payment per item (a
  database index); refunds cannot exceed the payment; an append-only, hash-chained audit log protected by database
  triggers; a live key refuses to run outside `APP_ENV=production`; test and live data never share a database;
  secrets are redacted from logs; redirects from the provider are refused. Validation refuses a setup where the
  people who pay can also create or edit the item they pay for (they could set their own price) unless you accept
  that risk explicitly.
- Scale: a Postgres job queue (`SKIP LOCKED` + leases), so any number of workers on any number of machines; the
  generated `docker-compose.yml`, `deploy/compose.worker.yml` (workers on another server), optional `deploy/k8s/`,
  `deploy/sql/roles.sql` (least-privilege logins) and `deploy/DEPLOYMENT.md` all come from one sizing calculation.
- Verified: each generated payments project passes its own tests (about 120) against a real PostgreSQL and a faithful
  stand-in for the provider's API; `uv run pytest tests/e2e/test_payments_stack.py` runs a Docker stack (PgBouncer,
  two workers, duplicate webhooks across replicas, a worker killed mid-job, a provider outage, the roles script,
  container hardening). 18 deliberately broken controls are all caught by those tests. **Not verified against the
  real Stripe or Razorpay**; supply your own test keys for that (see the generated `deploy/DEPLOYMENT.md`).

### File uploads

A project can accept **file uploads of any type** into an S3 bucket or any S3-compatible server (a MinIO you run,
Ceph, SeaweedFS, Garage). Every file is checked and **scanned for malware (ClamAV) before it is stored**. Design,
research, decisions and the verified / unverified list are in `STORAGE_PLAN.md`.

- Configure over the API: `PUT/GET /projects/{id}/storage` (S3 or MinIO-compatible, bucket, allowed types or any, size
  and quota limits, rate limit, proxy or presigned downloads, roles, audit retention),
  `GET .../storage/issues`, `GET .../storage/impact?action=` and `POST .../storage/enable|disable` with
  `{"confirm": true}`. The settings are part of `GET/PUT .../spec` (`storage`), and entities get a new field type,
  **`file`**, that holds the id of an uploaded file (checked on every write: it must exist, be clean, belong to the
  caller's tenant and be theirs or shared). **No bucket credential is stored in the builder or put in the zip**
  (`STORAGE_ACCESS_KEY_ID` / `STORAGE_SECRET_ACCESS_KEY`, or `*_FILE`; on AWS an IAM role).
- Generated routes: `POST /files` (multipart), `GET /files`, `GET /files/{id}`, `GET /files/{id}/download`,
  `DELETE /files/{id}`, and for the `operate` roles the audit trail, scanner/bucket health, quarantine and release.
- Safe by construction: the scan runs before anything is stored and a scanner that is down refuses the upload
  (never "assume clean"); the type comes from the file's bytes, never from `Content-Type` or the extension; keys are
  random and the client's file name is only cleaned for display; the size is capped while the body arrives; downloads
  are attachments with `nosniff` and a sandbox CSP; roles deny by default and a file you may not see answers like one
  that does not exist; an append-only, hash-chained audit trail (DB triggers, at least 365 days, no file names or
  contents) with a daily digest to keep elsewhere; erasure removes the bytes and keeps only a tombstone; a maintenance
  command rescans, retries deletions and cleans up after crashes. The zip contains `deploy/storage/STORAGE.md`
  (bucket setup, IAM and bucket policies, operations, erasure requests) and `docs/storage-security.md` (threat model).
- **MinIO note:** the MinIO community edition stopped publishing container images in October 2025 and its repository was
  archived, so "MinIO" here means any server that speaks the S3 API. The generated `docker-compose.yml` starts SeaweedFS
  as the local development store; production points `STORAGE_ENDPOINT_URL` at your own server.
- Libraries (researched): `boto3` (official AWS SDK; run in threads) and `python-multipart>=0.0.22` (earlier versions
  have two denial-of-service CVEs and a path-traversal CVE). The ClamAV client is about 100 lines of standard library,
  because the Python wrappers are unmaintained.
- Verified: each generated storage project passes its own tests (about 130) against a real PostgreSQL, a stand-in
  scanner over a real socket and an in-memory bucket; `uv run pytest tests/e2e/test_storage_stack.py` runs the real
  stack (API, PostgreSQL, **real ClamAV** and a **real S3-compatible server**): the EICAR test file is caught (also
  inside a zip) and never reaches the bucket, multipart upload, presigned links, a scanner outage and its recovery, a
  tampered object, the rescan command and deletion. **AWS S3 itself and a real MinIO were not available to the tests.**

### Authorization models (RBAC, ABAC, PBAC)
A generated project decides who may do what in one of three ways, chosen in the dashboard under
**Authorization** (or in the spec's `authorization.model`):

- **rbac** (default): roles with per-operation permissions and optional row rules (own records, own
  organisation). Unlisted operations stay public, as before; signed-out routes only exist here.
- **abac**: policies over attributes of the person (`id`, `email`, `roles`, `tenant_id`, sign-up fields),
  the record (its own fields plus `id`, timestamps, `created_by_id`) and the moment (`hour_utc`,
  `weekday_utc`, `client_ip`). Every policy applies to every signed-in person.
- **pbac**: the same policies with an `allow` / `deny` effect, attached to roles (or `*` for everyone).
  "PBAC" has no standard definition; this is the meaning used here.

Under abac and pbac: default deny, a matching deny always wins, conditions are plain JSON data (no code is
ever evaluated), lists, reads and writes are filtered in SQL and re-checked in Python, and the policy engine
(`app/core/authz_engine.py`) is copied byte for byte into the generated project, so what the builder
simulates is what ships. Multi-tenant projects stay scoped to the organisation before any policy runs.

Builder endpoints (all behind the project guard; a viewer may read and simulate, an editor may save):
`GET/PUT /projects/{id}/authorization` (`expected_version` guards against lost updates),
`GET .../authorization/issues`, `POST .../authorization/simulate` (decision plus a trace per policy and
comparison), `GET .../authorization/coverage` (entity by operation: closed / conditional / open),
`POST .../authorization/recommend` and `GET .../authorization/recommendation` (a fixed scoring table that lists
its reasons; no machine learning). The dashboard wraps these in a model picker with a questionnaire, a policy
editor with a condition builder and templates, the simulator and the coverage matrix.

Known limits: no signed-out routes under abac/pbac; conditions cannot look at a parent record's attributes;
an update must leave the row readable rather than satisfy the update policy a second time; behind a proxy run
uvicorn with `--proxy-headers` so `client_ip` is the caller's address (see MASTER_PLAN.md, L15-L20).

### Observability (OpenTelemetry)
Optional, per project (dashboard section **Observability**, or the spec's `observability` block). When on, the
generated service gets `app/core/telemetry.py`, `docs/OBSERVABILITY.md`, tests, and (with `local_stack`) a compose
overlay with a collector, Jaeger and Prometheus: `docker compose -f docker-compose.yml -f deploy/observability/compose.yml up`.

- **Collected**: a server span per request named after the route template, a span per SQL statement (placeholders,
  never values), request count and duration per route and status, a counter of policy denials, and JSON logs carrying
  `trace_id` / `span_id` / `request_id`. Never collected: bodies, headers, cookies, SQL parameter values.
- **Tuned by environment only** (`APP_OTEL_ENABLED` kill switch, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_TRACES_SAMPLER_ARG`,
  `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_HEADERS`): changing cost never needs a code change. No endpoint or credential is
  stored in the builder.
- **Secrets**: every span is scrubbed before export (secret-looking keys, token shapes, every query-string value) and the
  collector masks a second time. The generated tests send hostile payloads and assert nothing leaks.
- **Sizing**: give the expected peak requests per second and the dashboard suggests a sample ratio (rule of thumb: 4 spans
  per request, about 200 spans per second per small collector).
- Endpoints: `GET/PUT /projects/{id}/observability`, `GET .../observability/issues`.

Known limits: logs are not exported over OTLP (ship stdout JSON; they correlate by trace id); the sampler is head-based;
only the web process is instrumented (not the payments worker); see MASTER_PLAN.md L23-L29.

### CI/CD and cloud deployment (AWS, Azure, Google Cloud)
Optional, per project (dashboard section **Deploy**, or the spec's `deployment` block). When on, the generated project gets
GitHub Actions workflows (`ci.yml`, `deploy.yml`, `dependabot.yml`), Terraform in `deploy/<cloud>/` with one `.tfvars` per environment, a
one-time `bootstrap/` module, and `docs/DEPLOYMENT.md`.

- **CI**: lint, tests against PostgreSQL, `alembic check`, image build, vulnerability scan (fails on a fixable HIGH or CRITICAL), SBOM,
  `terraform fmt` and `validate`.
- **CD**: build once (tags immutable, image signed with cosign, provenance and SBOM attached), run migrations as a separate task with the *new*
  image before traffic moves, roll out, smoke test `/ready`. A push to `main` deploys the first environment; "Run workflow" promotes an
  existing tag to the next one without rebuilding. Rollback is automatic on AWS (deployment circuit breaker) and by revision on Azure and
  Cloud Run.
- **No cloud credentials anywhere**: pipelines use GitHub OIDC (AWS role, Azure federated credential, Google Workload Identity Federation),
  trusted for one repository and one GitHub environment, so production can require reviewers. Secrets live in the cloud's secret manager and
  are filled in by a person; Terraform only creates the containers and `DATABASE_URL`.
- **Security defaults**: private database (no public address), TLS required, encrypted storage, least-privilege service identity, deletion
  protection and longer backups where `deletion_protection` is on, state storage private and versioned, WAF on AWS outside dev, GitHub Actions
  pinned to commit SHAs.
- **Capacity is numbers**: a profile (small, medium, large) fills instances, CPU, memory and database size per environment; any number can be
  overridden, and the dashboard previews the resulting `.tfvars`. `POST /projects/{id}/deployment/plan` does the same over the API.
- Endpoints: `GET/PUT /projects/{id}/deployment`, `GET .../deployment/issues`, `POST .../deployment/plan`.

Checked in Docker with the real tools: `terraform fmt`, `init` and `validate` against the real provider schemas (aws 6, azurerm 5, google 8)
for every stack and bootstrap, and `actionlint` for the workflows (`tests/e2e/test_deploy_bundles.py`). **`terraform apply` has not been run
against a real account.** Not supported yet (validation refuses them): payments, file uploads with malware scanning, Redis token storage, a
Keycloak server of its own. See MASTER_PLAN.md L30-L38.

### Tests

```bash
uv run pytest tests/unit            # fast, no Docker
uv run pytest tests/api             # builder API against a Postgres testcontainer
                                    # (or set TEST_DATABASE_URL to a disposable
                                    #  postgresql+asyncpg:// database to skip Docker)
uv run pytest tests/e2e             # generated Blog/Library projects booted for real
```

`tests/e2e` needs Docker. `test_generated_project.py` applies the generated migration to a
Postgres container, checks it for drift and reversibility, and runs the generated project's
own smoke tests. `test_compose_stack.py` is the PLAN.md section 1 demo: build Blog through
the API, download the zip, `docker compose up --build`, drive the generated API over HTTP and
run `make test`'s command inside the stack (several minutes; skipped without `docker compose`).

### Dashboard and demo data

```bash
docker compose up -d          # builder API :8000, Postgres, and the dashboard on :5173
docker compose exec -e SEED_PASSWORD='a long passphrase' api python /app/scripts/seed.py   # signs in (or signs up) as demo@example.com and loads the demo projects
```

`scripts/seed.py` (standard library only; `--reset` recreates, `--base-url` points elsewhere,
`--email/--password` or `--token` choose who owns the demos)
creates **Helpdesk** (roles, invitations, email + SMS sign-in, custom registration fields and
every permission kind), **Vault** (RS256 + Redis), **Workspace** (multi-tenant), **Bookshop**
(plain CRUD, no auth), **SSO Hub** (Keycloak with Google and Entra ID logins) and **SSO Portal**
(a second platform on the same Keycloak realm). Open http://localhost:5173: each project has a
sidebar (Overview, Data model, Authentication, Keycloak, Payments, Roles & access, Generate). The Overview lists
what is left to do and links to the fix for every validation problem; after a download, the
Generate page lists the environment variables to set before running it.

## Stack

Python 3.12, uv, FastAPI, Pydantic v2, SQLAlchemy 2 (async) + asyncpg, Alembic,
PostgreSQL, structlog. Dev: pytest, pytest-asyncio, httpx, testcontainers, ruff, mypy.

## Run it

```bash
docker compose up --build
```

This starts Postgres, runs `alembic upgrade head`, and serves the API on
`http://localhost:8000` (docs at `/docs`).

```bash
curl http://localhost:8000/health   # {"status": "ok"}
curl http://localhost:8000/ready    # {"status": "ready"}  (round-trips the DB)

# Everything else needs an account. Sign up, then use the access token:
TOKEN=$(curl -s -X POST http://localhost:8000/account/register -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "a long passphrase here"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -X POST http://localhost:8000/projects -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"name": "Blog"}'
```

## Accounts, administration and API tokens

The builder itself is a multi-user platform. **Nothing except `/health`, `/ready` and the sign-in
endpoints is reachable without signing in**, and a project can only be seen by its members.

| Surface | Where | Who |
|---|---|---|
| Customer app | dashboard `/`, API `/account/*`, `/projects/...` | anyone with an account (sign-up is open by default) |
| Admin console | dashboard `#/admin`, API `/admin/*` | platform staff only: its own sign-in, tokens, cookie and look |

* **People**: `POST /account/register`, `/login`, `/refresh`, `/logout`, `GET /account/me`,
  `POST /account/password`. The access token (15 min) is kept in memory; the refresh token is an
  httpOnly `SameSite=Strict` cookie that rotates on every use (replaying a used one signs the whole
  session out). Five wrong passwords lock an account for 15 minutes; all failures look the same.
* **Projects have members** (`/projects/{id}/members`): `owner` (also manages people, credentials
  and deletion), `editor` (changes the model), `viewer` (read only). Someone else's project answers
  `404`, exactly like one that does not exist.
* **API tokens** (`/account/tokens`, Account page): for scripts, CI and tools such as Lovable.
  Scopes `read`, `write`, `generate` (a zip leaves the platform, so it is separate), optional pinning to
  one project, expiry up to a year. Shown once; only a hash is stored. They never work on `/admin`.
* **Admin console**: create people (temporary password shown once, change forced), suspend, change
  platform role (`platform_support` is read-only), reset passwords, end sessions, read the audit
  log. Administrators see project names, owners and sizes. They **cannot** open customer models,
  credentials or generated code.
* **Audit log** (`platform_audit_log`): sign-ins, failures, refused access, every successful project
  change, every admin action. Append-only (a database trigger refuses UPDATE and DELETE). Never
  contains passwords, tokens or request bodies.

First administrator: `docker compose exec api uv run python /app/scripts/create_admin.py you@example.com
--adopt-projects` (prompts for the password; `--adopt-projects` claims projects created before
accounts existed), or set `BUILDER_BOOTSTRAP_ADMIN_EMAIL` and `BUILDER_BOOTSTRAP_ADMIN_PASSWORD`
once. There is no default password anywhere.

Configuration (all environment variables, see `/admin` -> Settings for the live values):

| Variable | Default | Meaning |
|---|---|---|
| `SECRET_KEY` | dev value in compose | signs tokens and encrypts stored credentials. **Required outside `local`**: at least 32 characters, no placeholders (`openssl rand -base64 48`) |
| `BUILDER_ENVIRONMENT` | `local` | anything else turns on secure cookies, HSTS and hides `/docs` |
| `BUILDER_SIGNUP_MODE` | `open` | `closed`: only administrators create accounts |
| `BUILDER_CORS_ORIGINS` | `["http://localhost:5173"]` | explicit origins only (`*` is refused: cookies are used) |
| `BUILDER_ACCESS_TOKEN_MINUTES` / `_REFRESH_TOKEN_DAYS` / `_ADMIN_REFRESH_TOKEN_HOURS` | 15 / 14 / 12 | session lengths |
| `BUILDER_LOGIN_MAX_FAILURES` / `_LOCKOUT_MINUTES` | 5 / 15 | account lockout |
| `BUILDER_TRUST_PROXY_HEADERS` | `false` | set `true` only behind a proxy that overwrites `X-Forwarded-For` |
| `BUILDER_MAX_REQUEST_BYTES` | 10 MiB | larger bodies get `413` |

Known limits are tracked in `MASTER_PLAN.md` section 6 (no e-mail verification or e-mailed password
reset yet, no MFA, in-process rate limiting is per worker).

## Local development

```bash
uv sync                       # install deps (incl. dev group) into .venv
cp .env.example .env          # adjust BUILDER_DATABASE_URL if not using docker compose
export SECRET_KEY=...         # signs sign-in tokens, encrypts stored credentials; read from the environment
                               # (unset in BUILDER_ENVIRONMENT=local: a temporary key is generated)

uv run ruff check .           # lint
uv run mypy app alembic       # type check
uv run pytest                 # unit tests (no DB) + API tests (spin up a Postgres
                               # testcontainer automatically -- Docker must be running)

uv run alembic revision --autogenerate -m "message"   # new migration
uv run alembic upgrade head                            # apply migrations
```

## API surface

| Area | Endpoints |
|---|---|
| Health (open) | `GET /health`, `GET /ready` |
| Accounts (open to sign in) | `/account/register`, `/login`, `/refresh`, `/logout`, `/me`, `/password`, `/tokens` |
| Members | `GET/POST /projects/{id}/members`, `PATCH/DELETE /projects/{id}/members/{user_id}` |
| Admin console | `/admin/login`, `/users`, `/projects`, `/audit`, `/stats`, `/settings` |
| Authorization | `GET/PUT /projects/{id}/authorization`, `/authorization/issues`, `/simulate`, `/coverage`, `/recommend`, `/recommendation` |
| Observability | `GET/PUT /projects/{id}/observability`, `/observability/issues` |
| Deployment | `GET/PUT /projects/{id}/deployment`, `/deployment/issues`, `/deployment/plan` |
| Projects | `POST/GET /projects`, `GET/PATCH/DELETE /projects/{id}` |
| Entities | `POST/GET /projects/{id}/entities`, `GET/PATCH/DELETE /entities/{id}` |
| Fields | `POST/GET /entities/{id}/fields`, `PATCH/DELETE /fields/{id}` |
| Relations | `POST/GET /projects/{id}/relations`, `PATCH/DELETE /relations/{id}` |

Conventions: UUID ids, `limit`/`offset` pagination (`{items, total, limit, offset}`),
error body `{code, message, details[]}`, `422` for request validation, `404` for
missing resources, `409` for name/slug conflicts, `400` for a relation referencing an
entity outside its project. Projects use a `version` counter for optimistic locking —
`PATCH /projects/{id}` requires the current `version` in the body and 409s if stale.

## Project layout

```
app/
  main.py        # app factory, router registration
  config.py      # pydantic-settings, env prefix BUILDER_
  db.py          # async engine/session factory
  errors.py      # structured error envelope {code, message, details[]} + handlers
  exceptions.py  # AppError (framework-free, raised by services/)
  api/           # thin routers: health, projects, entities, fields, relations
  models/        # SQLAlchemy models for the builder's own tables + enums/mixins
  schemas/       # Pydantic request/response models per resource + Page[T]
  services/      # business logic (no FastAPI imports): one *_service.py per resource
  core/          # framework-free helpers; naming.py today, spec/validation in M2
alembic/         # migrations for the builder's own DB
tests/
  unit/          # pure-function tests (naming helpers so far)
  api/           # httpx + ASGITransport tests; conftest.py spins a Postgres
                 # testcontainer per session and overrides get_session per test
```

## Not yet

- The builder API itself has no authentication (by design for Phase 1 — see `PLAN.md`
  section 2); only the *generated* projects can have it.
- Multi-tenancy does not add Postgres row-level security as a second line of defence, there is
  no super-admin who spans tenants, and email addresses are unique across all tenants.
- Credentials saved with `PUT /projects/{id}/auth/secrets` are encrypted at rest on the builder
  but nothing in generation uses them (the zip never contains secrets), and the dashboard has no
  form for them. Treat that endpoint as a vault until a use for it, such as sending a test
  email or SMS before download, is built.
- Generated auth rate limits are counted in process memory (per worker).
- PATCH endpoints can't explicitly clear a nullable field back to `null` (only
  `exclude_unset` semantics); not needed until the spec/validation layer in M2
