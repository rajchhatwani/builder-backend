# Deploying Rupee Shop with payments

This file is generated from the load you described when you configured payments. Change the
inputs in the builder and generate again to get new numbers; nothing here is hand-edited.

> **The sizing below is an estimate, not a measurement.** It is a planning calculation with
> deliberately round numbers and headroom. Load-test on your own hardware (section 8) before you
> rely on it, and treat the first weeks in production as the real test.

## 1. What you are deploying

| Process | Command | What it does | Planned count |
|---|---|---|---|
| API | `uvicorn app.main:app` | Your endpoints, `/payments/...`, and the provider's webhook | 1 replica(s) × 1 server worker(s) |
| Payments worker | `python -m app.payments.worker` | Runs queued jobs (webhook events, refunds, retries) and the periodic jobs | 1 replica(s) × 8 job(s) at a time |
| Reconcile | `python -m app.payments.reconcile` | Compares with the provider and repairs drift. Also runs inside the workers every minute; run it by hand or from cron whenever you like | on demand |
| PostgreSQL | | The only shared state | 1 (replicated if you need availability) |

Everything is stateless apart from PostgreSQL. API replicas and workers never talk to each other,
so you can add or remove any of them at any time, on any machine that can reach the database and
(for workers and the API) the payment provider.

## 2. Your load, and what it means

| Input | Value |
|---|---|
| Peak payments per minute | 10 |
| Peak provider events per minute | 50 |
| Availability | single |
| Database `max_connections` | 100 |
| Webhook mode | **inline** (events are processed inside the webhook request: simple, fine at this volume) |

| Derived | Value |
|---|---|
| API replicas (autoscaling ceiling) | 1 (3) |
| Server workers per API replica | 1 |
| Worker replicas (autoscaling ceiling) | 1 (3) |
| Jobs per worker at once | 8 |
| Worker poll interval | 1.0 s |
| Connection pool per API server worker | 5 (+2 overflow) |
| Connection pool per worker | 10 |

### Database connections

Every process holds a pool of connections, and PostgreSQL has a hard limit. The plan needs about
**23** connections against a budget of **80**
(80 percent of `max_connections=100`).
There is no PgBouncer. If you add replicas beyond this plan, add up
`replicas × server workers × (pool + overflow)` for the API and `replicas × pool` for the workers,
plus about 6 for maintenance, and keep the total under 80.

Assumptions behind these numbers:
- A payment causes about 4 API requests and 5 provider events.
- One server worker is planned at 20 requests per second.
- One webhook job is planned at 0.25 seconds of work; workers run at about half of their capacity at the stated peak.
- At most 80 percent of the database's max_connections is planned.
- These are estimates, not measurements: load-test on your hardware before relying on them.

## 3. Before anything else: the settings

Copy `.env.example` to `.env` and fill it in. **Nothing secret is in this repository, and nothing
secret should ever be committed.** Provider keys come from the environment only (or from files: set
`RAZORPAY_KEY_SECRET_FILE=/run/secrets/key` instead of the value, which is how Docker and
Kubernetes secrets arrive).

| Setting | Meaning |
|---|---|
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` | Razorpay API key pair. `rzp_test_...` outside production, `rzp_live_...` in production. A live key anywhere but `APP_ENV=production`, or a test key in production, stops the app from starting. |
| `RAZORPAY_WEBHOOK_SECRETS` | The secret you typed when creating the webhook in the Razorpay dashboard (at least 16 characters). Several can be listed, comma separated, to rotate without downtime. |
| `APP_ENV` | `production` in production. |
| `DATABASE_URL` | Use the least-privileged login (`sql/roles.sql`) and TLS (`?ssl=require`, or better, verify the server certificate). |
| `PAYMENTS_WEBHOOK_MODE` | `inline` or `queued`. Default `inline`. |
| `PAYMENTS_WORKER_CONCURRENCY`, `PAYMENTS_POLL_INTERVAL_SECONDS` | Worker tuning. Defaults 8 and 1.0. |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_PGBOUNCER` | Connection pool of each process (section 2). |
| `UVICORN_WORKERS` | Server workers per API container. |
| `PAYMENTS_ALLOW_MODE_SWITCH` | Set to `true` for one start only, to move a database between test and live mode on purpose. |

Fixed when the project was generated (change them in the builder and generate again):
webhook timestamp tolerance 300 s, webhook body limit
262144 bytes, idempotency keys kept 48 h,
audit log kept at least 2555 days, currencies
INR, largest single payment 5000000 minor units.

## 4. Register the webhook with the provider

1. In Razorpay's dashboard add a webhook with the URL `https://<your-api-host>/payments/webhooks/razorpay`.
2. Select these events and no others:
   - `payment_link.paid`
   - `payment_link.expired`
   - `payment_link.cancelled`
   - `refund.created`
   - `refund.processed`
   - `refund.failed`
   - `payment.dispute.created`
   - `payment.dispute.won`
   - `payment.dispute.lost`
   - `payment.dispute.closed`
   - `payment.dispute.under_review`
   - `payment.dispute.action_required`
3. Enter a long random secret (at least 16 characters) when creating the webhook and put the same value in `RAZORPAY_WEBHOOK_SECRETS`.4. Test and live mode have separate webhooks and separate secrets. Register both, each with its own.

Razorpay sends no timestamp with a webhook. Replays are harmless anyway: each event id is accepted
once, and an event only makes the module ask Razorpay for the current state of the payment link.

The API verifies every webhook's signature and age before it reads anything else, refuses bodies
over the limit, answers every refusal with the same plain 400, and treats a duplicate event as
already handled. A webhook is treated as a hint: the module asks the provider for the object's
current state before changing anything.

## 5. Deploy

### One machine (Docker Compose)

```bash
cp .env.example .env        # fill it in
docker compose up --build -d
```

This starts the database, the API (with
1 server workers, the planned 1 × 1
folded into one container) and 1 worker replica(s). One machine is not
highly available; for that, use several machines or Kubernetes.

### Workers on other machines

Build the image once and push it to a registry your servers can reach. On each worker server copy
`deploy/compose.worker.yml` and a `.env`, then:

```bash
export APP_IMAGE=registry.example.com/rupee-shop:1.0.0
docker compose -f compose.worker.yml up -d
```

A worker server needs network access to the database and to the payment provider, and nothing
else. Start with the planned 1 worker replica(s) across your servers
(`WORKER_REPLICAS` in `.env`) and add more when `GET /payments/ops/status` shows jobs waiting.


### The database login

Run `deploy/sql/roles.sql` once as the database administrator (the file explains how, with the
passwords passed on the command line). Use the `_app` login for `DATABASE_URL` everywhere and the
`_migrator` login only for migrations. The `_app` login cannot change the schema and can only
append to the audit log.

## 6. Going from test to live

1. Create the live webhook in Razorpay and note its secret.
2. Use a **separate database** for live mode. The app records the mode in `pay_lock` and refuses to
   start on a database that holds the other mode's payments (`PAYMENTS_ALLOW_MODE_SWITCH=true` for
   one start overrides this on purpose; do not use it to mix modes).
3. Set `APP_ENV=production`, the live keys and the live webhook secret.
4. Make one small real payment and one refund, and watch it arrive (`GET /payments/<id>`, the audit
   verification endpoint, the Razorpay dashboard).

## 7. Upgrading

Order matters because workers and API replicas run the same code:

1. Run migrations (the `_migrator` login). Migrations here only add; they never rewrite payment data.
2. Roll out workers, then the API, one at a time. In-flight jobs finish (workers drain on SIGTERM
   for 25 s); a job whose worker is killed is retried by another after its 2-minute lease.
3. When Razorpay changes its API, re-read the field names the adapter relies on
   (`app/payments/providers/razorpay.py`) against its changelog before upgrading.

## 7b. Backups and restore

The payment tables are the system of record for what your customers paid. Back up PostgreSQL with
point-in-time recovery, test a restore, and keep the daily `audit_digest` log lines (they are
printed by the workers) in storage you control: they let you prove later that the audit table was
not rewritten, which a database administrator could otherwise do unnoticed. After a restore, run
`python -m app.payments.reconcile` to bring the records back in line with the provider.

## 8. Load-testing before you trust the numbers

Against a staging deployment pointed at Razorpay's **test mode**, create payments and send
signed test webhooks at the rate in section 2 for at least ten minutes while watching:
`GET /payments/ops/status` (`oldest_due_seconds` should stay near zero), database connections
(`SELECT count(*) FROM pg_stat_activity`), CPU and memory of each process, and the p95 latency of
`POST /payments`. Increase replicas or worker concurrency until the queue stays empty with
headroom, then write the numbers you measured next to the ones above.

## 9. Operating it

| You see | Meaning | Do |
|---|---|---|
| `oldest_due_seconds` growing | Workers are behind or down | Add workers; check their logs |
| `dead` jobs | A job failed 8 times | Read `last_error_code` in `GET /payments/ops/dead-jobs`, fix the cause, retry with `POST /payments/ops/dead-jobs/<id>/retry` |
| `provider_mismatch` in the audit log | The provider reported an amount or currency different from ours | Do not mark anything paid by hand; investigate in the provider dashboard |
| `duplicate_charge` | A payer was charged twice for one item | Refund the extra payment through the API or the dashboard |
| `payable_status_conflict` | A payment succeeded but the item was no longer in its waiting state (changed in between) | Decide by hand; the payment is real |
| audit verification says `intact: false` | A row of the audit log was altered or removed | Treat as a security incident; restore from backup and compare the daily digests |

Logs are JSON, one line per event, with a request id. Secrets and signatures are scrubbed before a
line is written; never add logging of request bodies or headers.

## 10. What this does and does not cover

- Card numbers never touch this system: the payer enters them on the provider's hosted page. That
  is what keeps your PCI scope small; whether you qualify for the smallest questionnaire (SAQ A)
  also depends on how your own site links to the checkout, which this code cannot see. Check with
  your provider or assessor.
- The audit log is tamper-evident, not tamper-proof against a database superuser. The daily digests
  are what closes that gap, if you store them elsewhere.
- Tested against a stand-in for the Razorpay API that follows the behaviour this code depends on, and
  against a real PostgreSQL. It has **not** been run against Razorpay itself unless you do that with
  your own test keys (expose your machine with a tunnel and point a test-mode webhook at `/payments/webhooks/razorpay`).
- Sizing numbers are estimates (section 2).
- Not included: subscriptions and invoices, payouts to other merchants (Stripe Connect, Razorpay Route), guest
  checkout without an account, embedded card fields, outbound webhooks to your own systems.
