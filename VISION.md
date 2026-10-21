# Backend Builder: Vision

Companion to `PLAN.md`. This document says **what we are building, why, and where it ends up**. `PLAN.md` says how Phase 1 gets built.

---

## 1. The problem

Every new project starts with the same backend work: schemas, CRUD, validation, pagination, auth wiring, roles, row-level access, caching, retries, background jobs, webhooks, Docker, tests. It is documented, repeatable and mostly deterministic, yet engineers rebuild it by hand each time. That costs days on every MVP before any product-specific work begins.

## 2. What we are building

An **internal backend generator with a control panel**.

You describe a backend once, as a structured spec (data model, relations, roles, access rules, endpoint options, jobs, webhooks). The system validates the spec and produces a **complete, runnable FastAPI project** you download and hand to developers. Setup is one command (`docker compose up`).

In one line: **spec in, production-shaped backend out, in minutes instead of days.**

### What it is not
- **Not a runtime platform.** Hasura and Directus interpret metadata at runtime, so your app depends on their engine, license and roadmap. We generate plain code that developers own, with no dependency on our tool after download.
- **Not an AI code writer.** Generation is deterministic templates. The same spec always produces the same output. No prompts, no variance.
- **Not a no-code app builder.** The output is a head start for engineers, not a replacement for them.
- **Not a universal framework.** One stack, done well, before any second one.

## 3. Who it is for

Primary user: you and your team, building MVPs in roughly 2 to 7 days. After the head start, developers continue normally in a standard FastAPI codebase. Customers never see the builder.

## 4. Core principles

1. **Spec is the product.** The spec format is the contract. The UI, the API and the generator are all views of it.
2. **Generate once, then developers own it.** No fighting over regeneration. Later additions come from incremental generation (add model, add endpoint) that never overwrites existing files.
3. **Deterministic and boring.** Established libraries and patterns. Same input, same output, byte for byte.
4. **Do not generate security cores.** Authentication is delegated to an identity provider (Keycloak first). We generate the integration, not the crypto.
5. **Enforce access in code, not in the UI.** Row-level rules must compile into enforced backend behavior (app-layer scoping plus Postgres RLS as a safety net).
6. **Extensible by modules.** Every capability (auth, jobs, caching, webhooks, WebSockets) is a feature module with its own spec section and templates.
7. **Prove it on real projects.** The roadmap is steered by what real past projects cannot yet express.

## 5. Architecture in three layers

1. **Spec**: one versioned document (`spec_version`) describing the whole backend.
2. **Generator**: a pure function from spec to file tree. No disk, no HTTP inside it. Feature modules plug into it.
3. **Builder API and dashboard**: FastAPI service that stores projects and specs, validates, previews and serves downloads. A web dashboard comes later and is purely a form editor over the same API.

Everything provider-specific (identity provider, broker, cache) sits behind adapters, so adding Auth0, Authentik or RabbitMQ later means adding an adapter, not rewriting a core.

## 6. What the generated backend contains (end state)

**Foundation (Phase 1)**
- FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic, PostgreSQL
- CRUD for every entity: list (pagination, filters, sorting, search), get, create, PUT, PATCH, DELETE, HEAD
- Relations: one-to-many, many-to-many, one-to-one
- Docker, Docker Compose, generated tests, README, health endpoints, structured logging, consistent errors

**Access control (Phase 2)**
- Identity via Keycloak (OIDC), with Google login brokered inside Keycloak
- Roles and permissions per endpoint
- Row-level rules declared in the spec and enforced in code and in Postgres RLS
- Multi-tenancy as a first-class option

**Platform features (Phase 3)**
- Celery and Redis: background jobs, retries with backoff, scheduled tasks, idempotency
- Declarative caching (TTL, keys, invalidate-on-write)
- Outbound webhooks: HMAC signing, retries, delivery log, dead-letter state. Inbound webhooks with signature verification
- WebSockets with a Redis pub/sub backplane
- Rate limiting, metrics, tracing, error reporting

**Hardening (Phase 4)**
- Generated tests extended: API fuzzing from the OpenAPI schema, security checks
- Safe schema evolution: migrations from spec diffs, with explicit rename handling
- Spec version migrators

**Control panel (Phase 5)**
- Web dashboard: model designer, role and row-rule editor, auth and feature toggles, preview of the file tree, spec diff and history, one-click download

## 7. Roadmap

| Phase | Outcome |
|---|---|
| 1 | Builder API plus generator produce a runnable CRUD backend with Postgres and Docker (`PLAN.md`) |
| 2 | Auth (Keycloak, Google), RBAC, row-level rules |
| 3 | Jobs, caching, webhooks, WebSockets, rate limiting, observability |
| 4 | Safe migrations, spec versioning, fuzz and security testing, real-project validation |
| 5 | Dashboard UI |
| Later | Additional IdPs (Auth0, Authentik), additional brokers, NoSQL module, other language stacks |

Rule: no phase starts until the previous phase's demo passes end to end.

## 8. How we will know it works

- **Time:** a typical MVP backend (about 10 entities, roles, jobs) generated and running in under an hour, versus days by hand
- **Fidelity:** 2 to 3 real past projects re-expressed in the spec, with the gaps documented and closed
- **Reliability:** generated projects boot and pass their own tests in CI, every time
- **Determinism:** identical specs produce byte-identical output
- **Ownership:** developers can modify generated code with no dependency on the builder

## 9. Known risks and honest limits

- **Spec design is the real difficulty.** Row rules, caching invalidation and schema evolution are per-project logic that must become declarative. Expect several spec revisions.
- **Injection through the spec.** Names and values end up in code and SQL, so strict validation and sandboxed templates are mandatory.
- **Schema changes after generation.** Renames and backfills are unsafe to automate blindly. Phase 4 addresses this explicitly.
- **Template maintenance.** Dependency updates and CVEs mean the templates need ongoing upkeep, and old generated projects will not update themselves.
- **Existing tools overlap.** Amplication, JHipster, Directus, Hasura and others cover parts of this. Our justification is a fixed Python stack, owned code, and the exact feature mix (row-level rules, jobs, webhooks) we repeat. We should periodically re-test those tools against our real projects and be willing to adopt one if it covers most of our needs.
- **Scope creep.** Supporting multiple databases, languages and IdPs early is the most likely way this stalls.

## 10. Non-goals (for now)

NoSQL, multiple languages, multiple frameworks, hosted multi-user SaaS, AI-assisted generation, marketplace of templates, visual workflow builders.

## 11. Open questions to settle as we go

1. Row rules: how expressive must the spec's rule language be before it becomes a mini programming language? (Aim: a small fixed set of rule types.)
2. Incremental generation: how do "add model" and "add field" work safely on a project that developers have already changed?
3. Deployment: do we stop at Docker Compose, or add Kubernetes or cloud templates later?
4. Does the builder itself ever become multi-user, and if so, how does that change its own auth?

## 12. Summary

We are building a **deterministic, spec-driven backend generator for one strong stack**, FastAPI and Postgres with Keycloak, Celery and Redis layered in over time. It outputs code developers fully own. The end vision is a dashboard where you define the model, roles and rules, click once, and download a backend that boots with one command and is ready for real product work.
