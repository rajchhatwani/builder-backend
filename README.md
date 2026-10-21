# Backend Builder

Internal FastAPI service that turns a structured spec (entities, fields, relations,
endpoint options) into a complete, runnable FastAPI project you download as a zip.
See `VISION.md` for the long-term product and `PLAN.md` for the Phase 1 build plan.

**Status: M1 (Builder CRUD) complete.** Projects, entities, fields, and relations are
fully manageable through the API with pagination, optimistic locking, and a
structured error envelope. Spec assembly/validation and generation land in M2+ (see
`PLAN.md` section 10).

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

curl -X POST http://localhost:8000/projects -H "Content-Type: application/json" \
  -d '{"name": "Blog"}'
```

## Local development

```bash
uv sync                       # install deps (incl. dev group) into .venv
cp .env.example .env          # adjust BUILDER_DATABASE_URL if not using docker compose

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
| Health | `GET /health`, `GET /ready` |
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

- Spec assembly, `PUT /projects/{id}/spec` import, and full validation (identifiers,
  reserved words, injection checks) (M2)
- Generator engine and feature modules (crud/docker/tests) (M3)
- Preview/download/generation-history APIs (M4)
- End-to-end proof: generate a project and boot it (M5)
- No authentication anywhere yet (by design for Phase 1 — see `PLAN.md` section 2)
- PATCH endpoints can't explicitly clear a nullable field back to `null` (only
  `exclude_unset` semantics); not needed until the spec/validation layer in M2
