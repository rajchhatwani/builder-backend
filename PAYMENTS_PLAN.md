# Payments option: design and implementation plan

Status legend: `[ ]` todo, `[~]` in progress, `[x]` done. **Update this file as you work** so a new chat can
resume from it. Read also `KEYCLOAK_PLAN.md` (the pattern and its gotchas), `PLAN.md`,
`examples/commerce/LIMITATIONS.md` and the memory notes (Docker workflow, Bash quirks: write patch scripts with
the Write tool, not heredocs with apostrophes).

## 1. Goal

A project can add **payments**. The generated zip then contains a payment module (hosted checkout, refunds,
disputes, signed provider webhooks, an audit trail), a **separately deployable worker**, and deployment files
(compose, optional Kubernetes) and notes **computed from the expected load** the client enters. Built for
security / compliance audits: card data never touches our code (PCI SAQ A territory; this is a design intent,
not a compliance opinion), no provider secret in the builder or the zip, fail closed, everything idempotent,
nothing sensitive in responses, logs, errors or the zip.

## 2. Decisions

Agreed with the user (2026-10-23): workers and extra processes are allowed and may run on other servers; scale
and security must be configurable and the deployment yml and notes must be generated from that configuration;
standard / already approved libraries only; nothing may leak.

Assumed defaults, because the user's reply did not cover them (**veto any of these**):

1. **Providers**: Stripe first (P4), Razorpay second (P8), PayPal later. One `PaymentProvider` interface.
2. **Merchant**: one provider account per deployment; multi-tenant projects mark every row with `tenant_id`.
   Per-tenant payouts (Stripe Connect / Razorpay Route, whose account ids are not secret) are deferred. Per-tenant
   API keys are never stored (env-only rule).
3. **Checkout**: hosted redirect only (Stripe Checkout Session). Razorpay needs its JS snippet in the client's
   frontend (documented). No embedded card fields in v1.
4. **v1 scope**: one-time payments, refunds, disputes recorded from webhooks (read-only). Subscriptions and
   invoices later (section 13). Signed-in payers only (the platform has no anonymous reads).
5. **Payable binding**: one entity per project (e.g. `Order`) with `amount_field`, currency (fixed or
   `currency_field`), and a status enum field with values for pending / paid / refunded / partially refunded.
6. **Money**: integer minor units + ISO 4217 code from a per-project allowlist; exact conversion only, never
   silent rounding; per-project maximum amount.
7. **Library policy**: stdlib (`urllib`, `hmac`, `hashlib`), SQLAlchemy/asyncpg, `cryptography` (approved).
   The job queue is a Postgres table (`FOR UPDATE SKIP LOCKED`), so no Redis/Celery is needed.
8. **Audit**: append-only table (DB triggers block UPDATE/DELETE), per-payment hash chain, daily digest job.
   Webhook payloads are stored reduced (allow-listed fields) plus the SHA-256 of the raw body, not raw.
9. **Test / live mode** comes from the key prefix, never from the spec; the app refuses mismatches.
10. **Real provider test**: automated against a faithful mock; an optional real Stripe test-mode run is gated on
    an env var holding the user's test key. Until then real-provider behaviour is **unverified** and will be
    reported as such.

## 3. Process model (what makes it scalable)

One image, several commands. All processes are stateless and share only Postgres, so any number can run on any
server.

| Process | Command | Scales by | Notes |
|---|---|---|---|
| `api` | `uvicorn app.main:app` | replicas x server workers | creates payments / refunds, receives webhooks |
| `payments-worker` | `python -m app.payments.worker` | replicas x concurrency | claims jobs with `SKIP LOCKED`, lease + retry |
| scheduler | same worker with `--schedule` (or every worker) | n/a | enqueues periodic jobs with a per-time-bucket `dedupe_key`, so any number of schedulers is safe and no leader election exists |
| `reconcile` | `python -m app.payments.reconcile` | one-shot | same code as the periodic job, for cron / manual runs |

**Job queue** `pay_jobs`: `id, type, payload (ids only, no PII), status queued|running|done|dead, run_at,
attempts, max_attempts, locked_by, locked_until, dedupe_key UNIQUE NULLS, last_error_code`. Claim =
`UPDATE ... WHERE id IN (SELECT ... WHERE status='queued' AND run_at<=now() ORDER BY run_at LIMIT n FOR UPDATE
SKIP LOCKED) RETURNING`. Lease expiry makes a killed worker's jobs claimable again. Backoff is exponential with
jitter, `dead` after `max_attempts` (logged at error level, listed by an admin endpoint). Handlers are idempotent.

**Webhook ingestion** has two modes (`PAYMENTS_WEBHOOK_MODE`): `queued` (default for medium+ profiles: verify
signature, insert event row, enqueue job, return 2xx fast; bursts are absorbed by the queue) and `inline` (small
profile: process in the request). Same handler either way.

**Sizing** (`app/core/payments_sizing.py`, pure function, builder side) turns the client's inputs
(`peak_payments_per_minute`, `peak_webhooks_per_minute` default 5x payments, `db_max_connections` default 100,
`availability: single|ha`, `server_count_hint`) into: api replicas, server workers per replica, DB pool size and
overflow per process, worker replicas / concurrency / batch size / poll interval, retention. It **checks that
total connections stay under 80 percent of `db_max_connections`** and otherwise outputs a PgBouncer
recommendation (transaction mode needs asyncpg `statement_cache_size=0`; generated config sets it when
`PGBOUNCER=true`). The formulas are estimates, labelled as such; P10 load-tests and calibrates them and the notes
must say what was measured and what was not.

**Generated deployment files** (all driven by the same numbers, deterministic):
`docker-compose.yml` (api, payments-worker with `deploy.replicas`, optional pgbouncer),
`deploy/compose.worker.yml` (a worker-only file for another server: needs only `DATABASE_URL` + provider env),
`deploy/k8s/` (optional: Deployment, HPA on queue depth is documented only, CronJob for reconcile,
PodDisruptionBudget, NetworkPolicy), `deploy/sql/roles.sql` (least-privilege DB roles: migrator, api, worker;
nobody but the migrator can DDL, nobody can UPDATE/DELETE the audit log), `deploy/DEPLOYMENT.md` (sizing table,
how to deploy, how to add a worker server, rolling upgrade order, backup / restore, secret rotation, runbooks).

## 4. Spec (contract between builder and generator)

```text
SpecAuth unchanged. New: Spec.payments: SpecPayments | None        (requires auth.enabled)

SpecPayments
  enabled: bool                         default true when block present
  provider: "stripe" | "razorpay"
  payable: { entity, amount_field, currency | currency_field, status_field, status_values{pending,paid,partially_refunded,refunded} }
  currencies: list[str]                 ISO 4217 allowlist, max 20
  max_amount_minor: int
  success_urls / cancel_urls: list[str] exact URLs; https except localhost; no wildcard / fragment / userinfo
  roles: { create: [..], read: [..], refund: [..], read_all: [..], operate: [..] }   empty = denied (fail closed)
  refund_approval_threshold_minor: int | None     two-person rule above it (approver != requester)
  scale: SpecPaymentsScale
  security: SpecPaymentsSecurity

SpecPaymentsScale
  profile: "small" | "medium" | "large" | "custom"
  peak_payments_per_minute, peak_webhooks_per_minute, db_max_connections, availability, pgbouncer, kubernetes
  (custom may override: api_replicas, server_workers, worker_replicas, worker_concurrency, pool_size, ...)
  webhook_mode: "inline" | "queued"; retention_days: {webhook_events, jobs, idempotency}

SpecPaymentsSecurity            every knob has a floor / ceiling; unsafe values are rejected, not clamped
  webhook_tolerance_seconds       30..600, default 300
  webhook_max_body_bytes          1 KiB..1 MiB, default 256 KiB
  webhook_ip_allowlist_enabled    default false (CIDRs come from env)
  idempotency_ttl_hours           24..168
  audit_retention_days            >= 365, default 2555 (7 years)
  audit_hash_chain                always true (not a knob)
  secrets_from_files              support *_FILE env vars (Docker/K8s secrets), default true
  hsts / security headers         reuse auth.security_headers_enabled
```

Never in the spec or the zip: API keys, webhook secrets, DB passwords. Env only
(`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRETS` comma list for rotation, optional `*_FILE` variants).

## 5. Phase 0: platform fixes (before payments)

- [x] Repository `_check_references` and many-to-many loader reject a parent that is outside the caller's tenant
      with 422 `invalid_reference` (same error as a missing parent, so nothing leaks). `Access.caller_tenant_id`
      carries the caller's tenant even for entities that are not tenant-scoped; a caller without a tenant cannot
      reference a tenant-scoped row (fail closed). Generated tests `test_<t>_cannot_point_at_another_tenants_*`
      and `test_*_cannot_link_another_tenants_*` (fixture `workspace_auth` now has a relation + a many-to-many);
      mutation check: removing the tenant condition makes all 3 fail. Goldens updated.
- [x] Numeric overflow: schemas now bound integer (int32) / bigint (int64) and decimal (18 digits, 6 places);
      a global `DataError` handler returns 422 `value_out_of_range` for anything else the database refuses (also
      query filters). **Behaviour change:** a decimal with more than 6 places is now rejected (422) instead of
      being rounded silently. Generated smoke test posts 10**30 to the first numeric field.
- [ ] Validation: payments is rejected if its payable entity has an operation with no roles (public). (Lands in P2.)
- [~] Re-run `examples/commerce/probe_limits.py` fk + overflow probes and record the new result in LIMITATIONS.md.
      Deferred to P10 (needs a rebuilt builder image + regenerated commerce stack); the generated tests above
      already reproduce the same attacks.

## 6. Builder side

### 6.1 Data model (P1)
- [ ] enums: `PaymentProvider`, `PaymentsProfile`, `PaymentsAvailability`, `WebhookMode`.
- [ ] table `project_payments_configs` (1:1 with project, cascade delete): provider, payable JSONB, currencies
      JSONB, max_amount_minor, urls JSONB, roles JSONB, threshold, scale JSONB, security JSONB, enabled.
- [ ] Alembic migration for it. `spec_service` exports / imports `payments`; a replace keeps the row.
### 6.2 API (P1) `app/api/payments.py`, `app/services/payments_service.py`
- [ ] `GET/PUT /projects/{id}/payments`; `GET /projects/{id}/payments/sizing` (derived numbers, warnings, no side
      effects); `GET .../payments/impact?action=`; `POST .../payments/enable|disable` with `{confirm:true}`.
- [ ] Disabling keeps the settings and tells the user that generated tables are never dropped.
- [ ] No secret fields exist anywhere in schemas or responses.
### 6.3 Validation (P2) `_check_payments`
- [ ] requires auth enabled; payable entity / fields exist with right types (decimal amount, enum status that
      contains the four values); no public operation on the payable entity; currency codes valid; URLs rules;
      roles exist and none empty; threshold >= 1; every numeric bound above; sizing sanity (replicas x pool <=
      80 percent of db_max_connections unless pgbouncer); `kubernetes`/`pgbouncer` only with consistent options;
      `multi_tenant` supported; provider-specific limits (currency support list per provider).

## 7. Generator side (generated project)

Feature module `app/core/generator/features/payments/` (module.py, templates/), plus edits to `docker` (compose,
env, Makefile, README) and `tests`. Files:

- [ ] `app/payments/{config,money,providers/base,providers/stripe,models,schemas,service,state,idempotency,audit,
      webhooks,router,jobs,worker,scheduler,reconcile,redact,locks}.py`
- [ ] `alembic/versions/0003_payments.py.j2` (tables, check constraints, audit triggers, indexes, payments lock row)
- [ ] `deploy/` files from section 3, `.env.example` entries, `Makefile` targets (`make worker`, `make reconcile`)
- [ ] `tests/payments/` (see section 9) including a stdlib `fake_provider.py` so users can run tests offline

### 7.1 Rules (fail closed)
- Money: `amount_minor BIGINT CHECK (>0)`, `currency CHAR(3)` allowlisted, `refunded_minor <= captured_minor`
  check; exponent table (0, 2, 3 decimals); exact conversion or 422 `amount_not_representable`; max amount.
- Create payment: `Idempotency-Key` required (8..128 chars); amount read from the payable row inside the caller's
  tenant and scope (never from the client); amount snapshot stored; row written `creating` BEFORE the provider
  call; provider idempotency key derived from our payment id; success / cancel URL chosen by name from the
  allowlist, never accepted raw (no open redirect).
- Idempotency table: key scope = tenant + user + route; stores request hash and the response; same key + other body
  = 422, in flight = 409, replay returns the stored response; expiry by job.
- State machine: only forward transitions via `UPDATE ... WHERE status IN (allowed)`; webhook = hint, ambiguous or
  out-of-order events re-fetch the object from the provider; terminal states cannot be left except refund /
  dispute bookkeeping. Payable status change happens in the SAME transaction with the same guard.
- Webhooks: raw bytes; size cap before reading more; HMAC-SHA256 constant-time compare against every configured
  secret; timestamp tolerance; livemode must match the lock; unique `(provider, event_id)` insert first (duplicate
  = 200 no-op); every failure returns one generic 400 with no reason (reason to the log as a code); unknown event
  types are stored and ignored; optional CIDR allowlist from env.
- Refunds: role-gated; amount <= refundable computed under `FOR UPDATE`; `Idempotency-Key`; optional two-person
  approval above the threshold (approver differs from requester, both audited).
- Test / live: key prefix decides; `APP_ENV=production` + test key, or live key outside production, aborts boot;
  `pay_lock` row records livemode and refuses a switch unless `PAYMENTS_ALLOW_MODE_SWITCH=true`.
- Tenancy: every query carries `tenant_id`; webhook processing takes the tenant from the stored payment row, never
  from event metadata.
- Leak prevention: responses contain our ids, status, amounts and the checkout URL only; provider error text is
  mapped to our codes (never passed through); no stack traces; a log filter redacts key / secret / signature
  patterns and request bodies and headers are never logged; settings objects redact secrets in `repr`; `*_FILE`
  secrets supported; `/docs` examples contain no real-looking keys; the container runs non-root with a read-only
  filesystem in the generated compose / k8s files; the audit log stores references, not PII.
- Retention jobs: expire idempotency keys, reduce webhook events and finished jobs after their retention, never
  touch the audit log before `audit_retention_days`.
- Audit: append-only `pay_audit_log` with per-payment hash chain (no global chain, which would serialise inserts),
  daily digest job logs a digest for external anchoring. **Limit to document**: a database superuser can still
  rewrite history; real tamper evidence needs the digests shipped off the box.

## 8. Providers

- [ ] Stripe (P4): Checkout Session (hosted), PaymentIntent lookup, Refund, Dispute events, `Stripe-Version`
      pinned as a constant (re-check on every bump, like the Keycloak tag), form-encoded requests with `urllib`,
      10 s timeout, TLS verified, retries only on network errors with the same idempotency key, `Stripe-Signature`
      (`t=`, `v1=`) check.
- [ ] Razorpay (P8): Orders API, checkout signature (`order_id|payment_id` HMAC), `X-Razorpay-Signature` webhooks,
      INR / paise rules, frontend snippet documented. Interface changes needed by it are made in P4's interface.

## 9. Tests

- Builder: validation per rule, sizing function (properties: connections bound, monotone in load), service
  (enable / disable / impact), spec round trip, generation goldens for `payments_stripe_small`,
  `payments_stripe_large`, `payments_multitenant`, API tests.
- Generated project (offline, fake provider): signature forgery matrix (tampered body, wrong secret, old / future
  timestamp, replay, multiple v1 values, missing header, huge body), duplicate and reordered events, idempotency
  matrix, money conversion table, state machine property test, tenant isolation (cross-tenant order, payment,
  refund, webhook), role matrix, test / live mismatch refusals, redaction tests (a secret placed in env never
  appears in any response, error, log line, `repr`, OpenAPI schema), queue tests (claim concurrency, lease
  expiry, backoff, dead letter, dedupe).
- Zip scan test (builder): no `sk_live|sk_test|whsec_|rzp_` style secret, no DB password, in any generated file.
- E2E (Docker, `tests/e2e/test_payments_stack.py`): mock provider container; stack with 2 api replicas + 2
  workers: concurrent duplicate webhooks across replicas process once; kill a worker mid-job and see recovery;
  provider timeout after charge creation then reconcile repairs; refund races cannot exceed the captured amount;
  worker-only compose file on a second compose project against the same DB; small load run to calibrate the
  sizing numbers (reported as measured on this machine, not a guarantee).
- Mutation checks by hand as in Keycloak (signature, timestamp, tenant, idempotency, state guard, refund bound,
  livemode, redaction): record N of N caught.
- Optional real Stripe test-mode run gated on `STRIPE_TEST_SECRET_KEY` (skipped if absent).

## 10. Dashboard (last)

- [ ] Sidebar section **Payments**: provider, payable binding, currencies, URLs, roles, thresholds; **Scale** step
      with the inputs, the derived sizing table, warnings, and a preview of the deployment shape; **Security**
      step showing the floors; impact dialog for enable / disable; post-download checklist (env vars, webhook URL
      and events to enable at the provider, DB roles script, worker server steps). `NextSteps.tsx` handles payments.

## 11. Phases and status

- [x] P0  platform fixes (section 5) (commerce probe rerun deferred to P10)
- [x] P1  builder: enums, model, migration `c7d2a41e9b05`, schemas, service, API, spec round trip, sizing function (`app/core/payments_sizing.py`)
- [x] P2  builder: validation (`app/core/validation_payments.py`, `app/core/currencies.py`) + tests (`tests/unit/test_payments_validation.py`, `test_payments_sizing.py`, `tests/api/test_payments.py`)
- [x] P3  generator core: money, models, migration `0003`, state machine, idempotency, audit (hash chain + triggers), redact (`app/core/redact.py`, all projects), lock, config
- [x] P4  Stripe adapter, routes, webhook ingestion, refunds, two-person approval (also enforced by a DB check constraint)
- [x] P5  Postgres queue (SKIP LOCKED + lease), worker, time-bucket scheduler, reconcile, retention, audit digest
- [x] P6  deployment generation (compose with workers + PgBouncer, `deploy/compose.worker.yml`, `deploy/k8s/`, `deploy/sql/roles.sql`, `deploy/DEPLOYMENT.md`, env, Makefile, README); Dockerfile now non-root with `UVICORN_WORKERS`
- [x] P7  generated tests (flow, security/ops), fake Stripe (`tests/payments_support.py`, HTTP, with control endpoints), goldens (`payments_stripe`, `payments_tenant`), secret scan (`tests/unit/test_payments_generation.py`)
- [x] P8  Razorpay adapter (Payment Links; webhooks by HMAC over the raw body + unique event id; refunds with `X-Refund-Idempotency`); one shared test suite now runs for both providers through the `tests/fake_<provider>.py` interface
- [x] P9  Docker e2e (`tests/e2e/test_payments_stack.py`, 10 tests: PgBouncer, 2 workers, 48 parallel duplicate webhooks, SIGKILL mid-job, provider outage, reconcile CLI, roles.sql, hardening, unsafe config) + 18 mutation checks, all caught
- [ ] P10 security audit pass (threat model `docs/payments-security.md` in the zip, own review, `/code-review`),
          load calibration of the sizing numbers, honest verified / unverified list in section 12
- [x] P11 dashboard (`frontend/src/components/PaymentsPanel.tsx`: provider, payable binding, money, roles table, load -> live sizing preview, security knobs, impact dialog; next steps after download)
- [x] P12 README section, seed demos (`pay-shop` Stripe, `rupee-shop` Razorpay), Postman folder, memory note

## 12. Verified / unverified (honest list)

**Verified by automated tests (all re-runnable):**
- Builder: settings API, switch with impact report, spec round trip, validation (76 rule tests), sizing properties.
- Generated projects `payments_stripe`, `payments_tenant`, `payments_razorpay` migrate, pass `alembic check`, downgrade, and pass
  their own ~120 tests on a real PostgreSQL: idempotency, parallel duplicate requests, one live payment per item, forged
  webhooks (17 Stripe / 13 Razorpay kinds, all refused identically), duplicate / out-of-order events, refunds incl. races and the
  two-person rule, disputes, tenants, audit immutability + tamper detection, job queue (exclusive claim, no waiting, lease
  takeover, backoff, dead letter), reconcile, retention, unsafe settings, secret redaction, redirects refused.
- Docker stack: see P9. Deployment YAML is parsed and checked against the sizing (`tests/unit/test_payments_generation.py`);
  every generated file is scanned for secret shapes.
- 18 mutants (signature, timestamp, body cap, dedupe, tenant filter, idempotency body check, refund limit, self-approval, live
  key, audit triggers, active-payable index, amount mismatch, redirects, checkout link visibility, literal secret redaction,
  SKIP LOCKED, payable status guard): every one is caught. (`SKIP LOCKED` is a throughput property, not correctness; the test
  asserts that a worker does not wait on a locked job.)

**NOT verified:**
- **Real Stripe / Razorpay.** Only stand-ins that follow the documented behaviour the adapters use. Stripe API version
  `2024-06-20` is pinned but unchecked. Razorpay facts confirmed from its docs: Payment Link create params, `X-Razorpay-Signature`
  over the raw body, `x-razorpay-event-id`, refund idempotency header, event names, refund / dispute fields, list links by
  `reference_id`. Razorpay facts NOT confirmed: the `POST /v1/payment_links/{id}/cancel` path and the exact error body shape.
  Run the generated tests with your own test keys before going live.
- Sizing numbers are estimates; the load calibration planned in P10 was NOT done (needs a quiet machine and real hardware).
  `DEPLOYMENT.md` says so in its first paragraph.
- Kubernetes manifests are YAML-valid and checked for consistency, never applied to a cluster. `NetworkPolicy` assumes names
  (`ingress-nginx`, `app: postgres`) the user must adapt.
- PgBouncer image `edoburu/pgbouncer:v1.25.1-p0` runs in the compose stack test; not tested under real load.
- The commerce probe re-run (P0) was not repeated; the equivalent attacks are generated tests.
- No browser test of the dashboard panel (it type-checks and builds; the API it calls is tested).

**Deviations from the first plan / things that changed:**
1. `Spec.payments` is top-level; no "custom" profile (a profile only fills empty numbers; any explicit number wins).
2. Added `allow_payer_edits` (security block): validation refuses a setup where payers can create / edit / delete the item they
   pay for, because the platform has no read-only fields. Found by the self-audit (P10).
3. Currencies: deliberately small list (no 3-decimal ones, no HUF/TWD/ISK/UGX).
4. Payments refuse the entity route name `payments`; table names `pay_*` are reserved.
5. The audit log is purged only by a deliberate, guarded operation (trigger needs a session setting and an age); there is no
   automatic purge job.
6. Providers are classified into neutral event kinds by the adapter; the event processor no longer knows provider event names.
7. `redact.py` and the pool / PgBouncer settings live in the shared CRUD templates (every generated project gets them), and the
   Dockerfile is now non-root with `UVICORN_WORKERS` for every project.
8. Per-tenant provider credentials / payouts (Connect, Route) remain out of scope, as agreed.

## 13. Later (not in this plan)
Subscriptions and invoices, Stripe Connect / Razorpay Route per-tenant payouts, PayPal, embedded card fields,
outbound webhooks to the client's systems (outbox), field-level read-only on the platform (recommended before
general availability: today anyone allowed to edit the payable's amount changes what is charged; mitigated by the
amount snapshot and a mismatch flag at capture), unique-per-tenant fields, `If-Match` versioning.

## 14. Resume checklist for a new chat
1. Read this file and `git status`; the checkboxes say where we stopped.
2. Docker Desktop workflow and test recipes are in memory (`dev-env-docker-workflow`).
3. Stdlib + approved libraries only; never put secrets in the zip; ask before any new library.
4. Before ending a session or when context is getting long: tick the boxes, add a line to section 15, and note
   anything half-done (file names, failing tests) so the next chat does not have to rediscover it.

**Paste this into a new chat:**
> We are building the Payments feature in D:\builder-backend. Read PAYMENTS_PLAN.md (design, decisions, phases,
> progress log in section 15), KEYCLOAK_PLAN.md (the pattern and its gotchas), examples/commerce/LIMITATIONS.md,
> and the memory notes (payments-plan, Docker workflow, Bash quirks). Run `git status`, find the first
> unchecked phase in section 11, and continue implementing until the whole plan is done. Update the plan
> checkboxes and section 15 as you go, and tell me honestly about deviations, limits and anything unverified.
> Hard rules: card data never touches our code; no provider secrets in the builder or the zip (env vars only);
> stdlib and already approved libraries only (ask before any new one); fail closed; verify webhooks by
> signature; everything idempotent; nothing sensitive in responses, logs or errors; scale and security are
> configurable and the deployment files and notes are generated from that configuration.

## 15. Progress log (newest last; one line per working session)

- 2026-10-23  Plan written and agreed in outline. No code yet. Pending items: user has not confirmed the assumed
  defaults in section 2 (treated as approved unless vetoed), and the uncommitted Keycloak tenant /
  custom-field work in the working tree has not been committed (suggested before P0).

- 2026-10-23  P0 done: tenant-checked references, numeric range 422. Unit suite 498 passed; e2e generated projects
  (workspace_auth, blog, library, keycloak_tenant, shop_auth) passed against Postgres. Gotcha: never run
  `ruff` on `tests/golden` (it leaves `.ruff_cache` folders that break the golden comparison). Next: P1.

- 2026-10-23  P1+P2 done. Spec: top-level `Spec.payments` (not under auth). A spec WITHOUT a payments block leaves
  the stored settings alone (like auth); disable via `POST .../payments/disable`. Profiles only fill empty load
  numbers (no "custom" profile; any explicit number or override wins). Currency table is deliberately small
  (no 3-decimal currencies, no HUF/TWD/ISK/UGX: provider special cases). Validation also requires: payable amount
  field `min_value > 0`, 3-char required currency field, no public operation on the payable entity, `get` enabled,
  tenant row rule in multi-tenant projects, `create`/`read` roles non-empty, security floors/ceilings, connection
  budget (or pgbouncer). Builder suites: unit 534+, api 228 passed. `alembic check` of the builder DB reports 4
  pre-existing project_id index drifts (not from payments). Gotcha: `ruff format` is not enforced repo-wide.
  Next: P3 generator core.

- 2026-10-23  P3-P7 done in one pass. Generated suites: `payments_stripe` 113 tests, `payments_tenant` 122 tests
  (run against Postgres via `tests/e2e/test_generated_project.py`). Bugs found by those tests and fixed: keyword
  collision in `_find_payment`, ORM attribute read after rollback, rollback expiring the caller's user object in
  the idempotent replay path, stale cached provider after a settings reload (rotation), IP allowlist in test env.
  Design points worth knowing: `Spec.payments` is top-level; the payments tables are `pay_*`; a webhook is a hint
  (the adapter re-fetches the object); `FAILED/CANCELED/EXPIRED -> SUCCEEDED` is allowed so real money is never
  hidden; the audit table has a per-payment hash chain and `UPDATE/DELETE/TRUNCATE` triggers. The Stripe API
  version is pinned to `2024-06-20` in `providers/stripe.py` and **has not been checked against real Stripe**.
  Dev loop for generated projects: scratchpad `dev_gen.py` + `dev_run.sh` (a throwaway `postgres:16-alpine` named
  `paydev` on port 55434); NEVER run ruff on `tests/golden` without `--no-cache`.
  Next: P9 stack test (`tests/e2e/test_payments_stack.py`), P8 Razorpay (neutral event kinds refactor first),
  P10 audit, P11 dashboard, P12 docs.

- 2026-10-23  P8-P12 done. Self-audit found 4 issues, all fixed with tests: payers able to set the price (new validation rule +
  `allow_payer_edits`), redirects followed by urllib (credential leak risk), staff seeing other people's checkout links, provider
  URL not checked for https in production. Final verification run: see the last entry once it finishes. Remaining ideas, none
  required: real-provider test run with the user's test keys, load calibration, `docs/payments-security.md` threat model in the
  zip, subscriptions (section 13).

## 16. Open decisions (answer when convenient; defaults in section 2 apply meanwhile)
- Providers order (Stripe then Razorpay assumed). Single merchant account vs per-tenant payouts (single assumed).
- Number of payable entities (one assumed). Refund roles and two-person approval threshold (none by default).
- Audit and webhook payload retention periods (audit 7 years, reduced payload assumed).
- Whether a Stripe / Razorpay test key will be provided for the optional real-provider run.
