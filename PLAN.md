# Backend Builder: Phase 1 Plan

Working name: **Backend Builder**. An internal FastAPI service. You describe a backend (entities, fields, relations, endpoint options) through REST APIs, then the service generates a complete FastAPI project and returns it as a zip. Tested through Postman. No UI, no CLI, no auth in this phase.

> Use this file as `PLAN.md` in the repo root. Tell Claude Code: "Read PLAN.md. Work one milestone at a time. Stop after each milestone and show me how to verify it."

---

## 1. Goal and definition of done

**Goal:** a working core. Define a data model through the API, download a runnable backend.

**Phase 1 is done when this demo works end to end:**
1. In Postman, create a project "Blog" with entities `User`, `Post`, `Comment`, including fields, one-to-many relations and a many-to-many (`Post` <-> `Tag`).
2. `POST /projects/{id}/validate` returns no errors.
3. `GET /projects/{id}/generate/download` returns a zip.
4. Unzip, run `docker compose up`, and the generated API serves full CRUD (list with pagination/filter/sort, get, create, PUT, PATCH, DELETE, HEAD) with a working Postgres and an applied migration.
5. The generated project's own smoke tests pass.

## 2. Scope

**In scope**
- Builder API with its own Postgres DB (projects, entities, fields, relations, generation history)
- Spec assembly, strict validation, deterministic generation, zip download
- Generated project: FastAPI + SQLAlchemy 2 (async) + Alembic + Postgres + Docker Compose + tests + README
- Health endpoints, structured errors, OpenAPI docs, a Postman collection

**Out of scope (Phase 2+, but leave hooks)**
- Authentication and authorization (Keycloak, RBAC, row-level rules)
- Celery/Redis jobs, caching, webhooks, WebSockets, rate limiting
- NoSQL, other languages, dashboard UI, multi-tenancy
- Spec version migrators, diff-based migrations for schema changes

## 3. Key decisions

| Decision | Choice | Why |
|---|---|---|
| Builder storage | Normalized tables (projects, entities, fields, relations) | Granular endpoints now and a form-based dashboard later |
| Spec | Assembled on demand, **snapshotted as JSONB on every generation** | Reproducible output, history, diffing later |
| Generation | Pure function: `generate(spec) -> dict[path, content]` | No disk or HTTP inside; API zips it; testable with golden files |
| Templates | Jinja2 `SandboxedEnvironment` | Spec values land in code, so reduce injection risk |
| Initial migration | **Rendered directly from the spec** (not Alembic autogenerate) | Deterministic, no DB needed at generation time |
| Features | Generator is split into feature modules (`crud`, `docker`, `tests`) behind one interface | Phase 2 adds `auth`, `jobs`, `webhooks` as new modules |
| Ownership | Generated code is generated once and then owned by developers | Avoids the regeneration-merge problem |

## 4. Tech stack (builder service)

Pin versions at scaffold time (`uv add`) and commit the lockfile. Do not guess versions; check PyPI.

- Python 3.12+, **uv** for packaging
- FastAPI, Pydantic v2, pydantic-settings, Uvicorn
- SQLAlchemy 2.x async + asyncpg, Alembic
- PostgreSQL (docker compose for local)
- Jinja2
- structlog
- Tests: pytest, pytest-asyncio, httpx, testcontainers-python
- Quality: ruff, mypy, pre-commit

## 5. Repo layout

```
backend-builder/
  app/
    main.py                 # app factory, routers, error handlers
    config.py               # pydantic-settings
    db.py                   # async engine/session
    api/                    # thin routers only
      projects.py entities.py fields.py relations.py spec.py generate.py health.py
    models/                 # SQLAlchemy models (builder's own tables)
    schemas/                # Pydantic request/response models
    services/               # business logic (no FastAPI imports)
      project_service.py spec_service.py
    core/
      spec_models.py        # Pydantic models defining the SPEC (the contract)
      validation.py         # validate(spec) -> list[ValidationIssue]
      naming.py             # identifier rules, reserved words, case conversion
      generator/
        engine.py           # generate(spec) -> FileTree; runs feature modules
        base.py             # FeatureModule protocol
        features/
          crud/ docker/ tests/   # each: module.py + templates/
  alembic/
  tests/
    unit/ api/ golden/ e2e/
  docker-compose.yml  Dockerfile  pyproject.toml  PLAN.md  README.md
  postman/backend-builder.postman_collection.json
```

Rule: `core/` never imports FastAPI or the DB. `api/` has no business logic.

## 6. Builder data model

- **projects**: id (uuid), name, slug, description, db_engine (`postgres` only for now), created_at, updated_at
- **entities**: id, project_id, name (PascalCase), table_name, plural_path (e.g. `posts`), options JSONB (see below)
- **fields**: id, entity_id, name (snake_case), type, required, unique, indexed, default, max_length, min/max, enum_values JSONB, position
- **relations**: id, project_id, kind (`one_to_many`, `many_to_many`, `one_to_one`), from_entity_id, to_entity_id, from_name, to_name, on_delete (`cascade|set_null|restrict`), required
- **generations**: id, project_id, spec_snapshot JSONB, spec_hash, file_manifest JSONB, created_at

Every entity automatically gets `id` (uuid pk), `created_at`, `updated_at`. These cannot be redefined by users.

**Entity options (JSONB):** enabled operations (`list, get, create, replace, update, delete, head`), filterable fields, sortable fields, searchable fields, default page size, max page size, soft_delete (bool).

**Field types:** `string, text, integer, bigint, float, decimal, boolean, date, datetime, uuid, json, enum`.

## 7. Builder API (Postman surface)

| Area | Endpoints |
|---|---|
| Health | `GET /health`, `GET /ready` |
| Projects | `POST/GET /projects`, `GET/PATCH/DELETE /projects/{id}` |
| Entities | `POST/GET /projects/{id}/entities`, `GET/PATCH/DELETE /entities/{id}` |
| Fields | `POST/GET /entities/{id}/fields`, `PATCH/DELETE /fields/{id}` |
| Relations | `POST/GET /projects/{id}/relations`, `PATCH/DELETE /relations/{id}` |
| Spec | `GET /projects/{id}/spec` (assembled), `PUT /projects/{id}/spec` (import whole spec, replaces model) |
| Validate | `POST /projects/{id}/validate` |
| Generate | `POST /projects/{id}/generate/preview` (file paths + sizes), `GET /projects/{id}/generate/download` (zip), `GET /projects/{id}/generations` |

Conventions: UUID ids, `limit/offset` pagination on lists, consistent error body `{code, message, details[]}`, `422` for validation, `409` for conflicts, ETag or `version` on projects for optimistic locking (simple counter is fine).

## 8. Validation rules (non-negotiable)

Run on `validate`, `preview`, `download`, and `PUT spec`. Return **all** issues, each with `path`, `code`, `message`.

- Identifiers: strict regex (`^[A-Za-z][A-Za-z0-9_]*$`), length limit, **no Python keywords/builtins, no SQL reserved words**, no collisions with auto fields
- Unique names: entities per project, fields per entity, relation names per entity, table names
- Relation targets exist, no ambiguous duplicate relations, many-to-many join table name derived deterministically
- Enum has at least one value, defaults match field type, min/max valid
- Filterable/sortable/searchable fields exist and have compatible types
- Spec values never build file paths. Paths come only from templates plus validated identifiers
- Sizes: cap entities, fields per entity, string lengths

## 9. Generated project (what the zip contains)

```
<slug>/
  app/
    main.py config.py db.py
    models/    (SQLAlchemy 2 models, one file per entity)
    schemas/   (Pydantic Create / Update / Read per entity)
    routers/   (one router per entity)
    crud/      (generic repository + per-entity thin classes)
    core/      (pagination, filtering, sorting, errors, logging)
  alembic/     (env.py + 0001_initial.py rendered from spec)
  tests/       (smoke test per entity: create/get/list/patch/delete)
  Dockerfile docker-compose.yml .env.example Makefile README.md pyproject.toml
  extension points: app/hooks/ (empty, documented) and app/custom_routers/ (auto-included)
```

Behaviors per entity (per enabled operation): `GET /{plural}` with limit/offset, filters, sort, search; `GET /{plural}/{id}`; `POST`; `PUT` (full replace); `PATCH` (partial); `DELETE`; `HEAD /{plural}/{id}`. Relations expose nested ids on read and accept ids on write. Health endpoints, request-id middleware, structured logging, CORS config from env, consistent error format.

Run experience: `docker compose up --build` starts Postgres and the API, runs `alembic upgrade head` on start, serves docs at `/docs`.

## 10. Milestones (give Claude Code one at a time)

**M0: Scaffold.** Repo, uv, FastAPI app factory, config, async DB, Alembic, docker-compose (builder + postgres), `/health` + `/ready`, ruff/mypy/pytest wired, structured error handler.
*Accept:* `docker compose up` works, `/health` 200, `pytest` green, CI-ready commands in README.

**M1: Builder CRUD.** Models, schemas, services and routers for projects, entities, fields, relations. Auto-fields, pagination, error format, optimistic version on projects.
*Accept:* Postman can build the Blog model fully. API tests cover happy paths, conflicts and 404s.

**M2: Spec and validation.** `core/spec_models.py`, spec assembly, `PUT spec` import, `validate` with the full rule set above.
*Accept:* Round trip (`GET spec` -> `PUT spec` on a new project) yields an identical spec. Unit tests per validation rule, including injection attempts like `x"; import os`.

**M3: Generator engine.** `FeatureModule` protocol, engine, `crud` + `docker` + `tests` modules, templates, deterministic ordering, sandboxed Jinja, initial migration renderer.
*Accept:* Golden-file tests for a fixture spec. Same spec gives byte-identical output twice. Generated code passes `py_compile` and `ruff check`.

**M4: Generation APIs.** `preview`, `download` (in-memory zip), `generations` history with spec snapshot and hash.
*Accept:* Download works in Postman. History lists snapshots.

**M5: End-to-end proof.** E2E test (testcontainers): generate Blog, boot generated stack, run its smoke tests and a CRUD flow. Export Postman collection into `postman/`. Write README.
*Accept:* The Phase 1 demo in section 1 passes from a clean checkout.

## 11. Testing strategy

- **Unit:** naming/validation rules, spec models, each feature module
- **Golden files:** fixture specs (minimal, blog, edge cases) compared to stored expected output
- **API tests:** httpx against the app with a test DB
- **E2E:** generated project booted for real. This is the only test that proves generated code works.
- Add a second fixture spec (not Blog) early so templates aren't overfit to one example.

## 12. Known risks to handle now

- **Identifier injection** into templates and migrations (section 8)
- **Reserved words**: a field named `class`, `order` or `user` breaks Python or SQL
- **Many-to-many naming** and join-table collisions
- **Generated code drifting from templates**: golden tests catch this
- **N+1 queries** in nested relation reads: use explicit eager loading from the spec's relations
- **Scope creep**: no feature outside section 2 until M5 passes

## 13. Phase 2 hooks (design now, build later)

- Spec has `features: []` and an `auth` block reserved but ignored by the generator
- Roles and row rules will be new spec sections compiled by a new `auth` feature module
- Celery, webhooks, WebSockets, caching each become a feature module with its own templates and spec section
- Spec carries `spec_version: 1` from day one

## 14. Rules for Claude Code

1. Work one milestone at a time. Stop and summarize after each.
2. Do not add libraries not listed here without asking. Check PyPI for current versions rather than assuming.
3. Keep `core/` free of FastAPI and DB imports.
4. Every validation rule gets a test. Every template change updates golden files deliberately.
5. No placeholders or fake implementations. If something is deferred, say so in the README under "Not yet".
6. Write migrations for builder tables with Alembic. Never edit applied migrations.
