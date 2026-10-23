"""Turns the expected load of a payments project into a deployment shape.

Pure and deterministic: the same `SpecPaymentsScale` always gives the same numbers, so generated
compose files, Kubernetes manifests and DEPLOYMENT.md agree with the builder's sizing endpoint.

**These are planning estimates, not measurements.** The constants below are round figures chosen to
leave headroom (about 40 percent utilisation at the stated peak). The Docker load run planned in
PAYMENTS_PLAN.md (P10) is meant to check them on one machine; until then nothing here is a promise
about throughput on the client's hardware. Anything the user sets explicitly (`api_replicas`,
`worker_concurrency`, ...) overrides the computed value.
"""

import math
from dataclasses import asdict, dataclass

from app.core.spec_models import SpecPaymentsScale

# Peak payments per minute used when the user gives none, by profile.
PROFILE_PAYMENTS_PER_MINUTE = {"small": 10, "medium": 120, "large": 1200}
WEBHOOKS_PER_PAYMENT = 5  # created, succeeded, charge events, refund events, a retry or two
API_REQUESTS_PER_PAYMENT = 4  # create, a few status reads
API_RPS_PER_SERVER_WORKER = 20  # planning figure for an async worker that is mostly waiting on I/O
MAX_SERVER_WORKERS_PER_REPLICA = 4
JOB_SECONDS = 0.25  # one webhook job: a few queries and sometimes a provider lookup
DEFAULT_WORKER_CONCURRENCY = 8
DEFAULT_POOL_SIZE = 5
MIN_POOL_SIZE = 2
CONNECTION_BUDGET_SHARE = 0.8  # never plan to use more than this share of max_connections
OVERHEAD_CONNECTIONS = 6  # migrations, a psql session, monitoring
INLINE_WEBHOOKS_PER_MINUTE = 100  # above this, webhooks are queued by default
QUEUE_LIMIT_JOBS_PER_SECOND = 500  # a Postgres queue is a poor fit well before this

ASSUMPTIONS = (
    f"A payment causes about {API_REQUESTS_PER_PAYMENT} API requests and "
    f"{WEBHOOKS_PER_PAYMENT} provider events.",
    f"One server worker is planned at {API_RPS_PER_SERVER_WORKER} requests per second.",
    f"One webhook job is planned at {JOB_SECONDS} seconds of work; workers run at about half "
    "of their capacity at the stated peak.",
    f"At most {int(CONNECTION_BUDGET_SHARE * 100)} percent of the database's max_connections "
    "is planned.",
    "These are estimates, not measurements: load-test on your hardware before relying on them.",
)


@dataclass(frozen=True)
class PaymentsSizing:
    payments_per_minute: int
    webhooks_per_minute: int
    webhook_mode: str
    api_replicas: int
    server_workers: int
    pool_size: int
    max_overflow: int
    worker_replicas: int
    worker_concurrency: int
    worker_pool_size: int
    poll_interval_seconds: float
    batch_size: int
    api_replicas_max: int  # autoscaling ceilings, used by the Kubernetes manifests
    worker_replicas_max: int
    total_db_connections: int  # what the database would see
    connection_budget: int
    needs_pgbouncer: bool  # the plan does not fit without a pooler
    pgbouncer_pool_size: int | None
    warnings: tuple[str, ...]
    assumptions: tuple[str, ...] = ASSUMPTIONS

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def effective_payments_per_minute(scale: SpecPaymentsScale) -> int:
    if scale.peak_payments_per_minute is not None:
        return scale.peak_payments_per_minute
    return PROFILE_PAYMENTS_PER_MINUTE.get(scale.profile, PROFILE_PAYMENTS_PER_MINUTE["small"])


def effective_webhooks_per_minute(scale: SpecPaymentsScale) -> int:
    if scale.peak_webhooks_per_minute is not None:
        return scale.peak_webhooks_per_minute
    return effective_payments_per_minute(scale) * WEBHOOKS_PER_PAYMENT


def size(scale: SpecPaymentsScale) -> PaymentsSizing:
    payments = effective_payments_per_minute(scale)
    webhooks = effective_webhooks_per_minute(scale)
    ha = scale.availability == "ha"
    warnings: list[str] = []

    mode = scale.webhook_mode or ("inline" if webhooks <= INLINE_WEBHOOKS_PER_MINUTE else "queued")

    # --- API processes
    api_rps = (API_REQUESTS_PER_PAYMENT * payments + webhooks) / 60
    workers_needed = max(1, math.ceil(api_rps / API_RPS_PER_SERVER_WORKER))
    floor_replicas = 2 if ha else 1
    api_replicas = scale.api_replicas or max(
        math.ceil(workers_needed / MAX_SERVER_WORKERS_PER_REPLICA), floor_replicas
    )
    server_workers = scale.server_workers or max(1, math.ceil(workers_needed / api_replicas))

    # --- worker processes (always at least one: maintenance, reconcile, retention)
    concurrency = scale.worker_concurrency or DEFAULT_WORKER_CONCURRENCY
    job_rate = 0.0 if mode == "inline" else webhooks / 60
    capacity_per_replica = concurrency / JOB_SECONDS / 2  # jobs per second at half load
    worker_replicas = scale.worker_replicas or max(
        math.ceil(job_rate / capacity_per_replica), floor_replicas
    )
    if job_rate > QUEUE_LIMIT_JOBS_PER_SECOND:
        warnings.append(
            "This load is beyond what a Postgres-backed queue is meant for; plan a message broker "
            "instead (not part of this generator yet)."
        )

    # --- database connections
    budget = int(scale.db_max_connections * CONNECTION_BUDGET_SHARE)
    pool = scale.pool_size or DEFAULT_POOL_SIZE
    overflow = max(1, pool // 2)
    worker_pool = concurrency + 2

    def demand(pool_size: int, max_overflow: int) -> int:
        api = api_replicas * server_workers * (pool_size + max_overflow)
        return api + worker_replicas * worker_pool + OVERHEAD_CONNECTIONS

    total = demand(pool, overflow)
    needs_pgbouncer = False
    pgbouncer_pool: int | None = None
    if scale.pgbouncer:
        # The pooler multiplexes: the database only sees the pooler's own pool.
        pgbouncer_pool = max(MIN_POOL_SIZE, budget - OVERHEAD_CONNECTIONS)
        total = min(total, pgbouncer_pool + OVERHEAD_CONNECTIONS)
    elif total > budget and scale.pool_size is None:
        pool, overflow = MIN_POOL_SIZE, 0  # shrink the pools before asking for more machinery
        total = demand(pool, overflow)
        if total <= budget:
            warnings.append(
                f"Per-process connection pools were reduced to {pool} to fit the database's "
                f"{scale.db_max_connections} connections; consider PgBouncer for more headroom."
            )
    if not scale.pgbouncer and total > budget:
        needs_pgbouncer = True
        warnings.append(
            f"The plan needs {total} database connections but only {budget} fit in "
            f"{scale.db_max_connections}. Turn on PgBouncer, raise max_connections, or reduce "
            "replicas."
        )

    poll = (0.2 if job_rate > 50 else 0.5) if job_rate > 5 else 1.0
    if ha:
        warnings.append(
            "High availability needs the replicas to run on separate machines or zones and a "
            "replicated Postgres; the generated files cannot arrange that for you."
        )

    return PaymentsSizing(
        payments_per_minute=payments,
        webhooks_per_minute=webhooks,
        webhook_mode=mode,
        api_replicas=api_replicas,
        server_workers=server_workers,
        pool_size=pool,
        max_overflow=overflow,
        worker_replicas=worker_replicas,
        worker_concurrency=concurrency,
        worker_pool_size=worker_pool,
        poll_interval_seconds=poll,
        batch_size=concurrency,
        api_replicas_max=max(api_replicas * 2, api_replicas + 2),
        worker_replicas_max=max(worker_replicas * 2, worker_replicas + 2),
        total_db_connections=total,
        connection_budget=budget,
        needs_pgbouncer=needs_pgbouncer,
        pgbouncer_pool_size=pgbouncer_pool,
        warnings=tuple(warnings),
    )
