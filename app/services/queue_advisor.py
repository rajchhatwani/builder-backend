"""Queue advisor: which queue technology fits the declared requirements. A pure function: no I/O, no clock.

Postgres (the app's own database, FOR UPDATE SKIP LOCKED) is the default and wins unless a requirement
forces something else. The thresholds are deliberately conservative and written down here, so a
recommendation can always be explained by the reasons it returns:

  * kafka          replay of multiple consumers, or sustained throughput above KAFKA_THROUGHPUT, or
                   per-key ordering above POSTGRES_THROUGHPUT, or a backlog above KAFKA_BACKLOG
  * rabbitmq       several independent consumers of one message (routing), cross-service delivery above
                   CROSS_SERVICE_THROUGHPUT, or low latency that must also be durable
  * redis_celery   best-effort work that needs a dispatch latency Postgres polling cannot give, or best-effort
                   throughput above POSTGRES_THROUGHPUT
  * postgres       everything else (delayed jobs, durability, transactional enqueue come for free)

Only `postgres` is implemented by the builder today; the result says so when it recommends anything else.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Backend = Literal["postgres", "redis_celery", "rabbitmq", "kafka"]

POSTGRES_THROUGHPUT = 1_000.0  # sustained jobs/s one Postgres queue handles comfortably
KAFKA_THROUGHPUT = 5_000.0  # sustained jobs/s beyond which a log (partitions) is the right tool
LOW_LATENCY_MS = 20.0  # p99 dispatch latency below which polling a database is not enough
CROSS_SERVICE_THROUGHPUT = 200.0
POSTGRES_BACKLOG_WARN = 1_000_000
KAFKA_BACKLOG = 50_000_000
IMPLEMENTED: tuple[Backend, ...] = ("postgres",)


class QueueRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    throughput_per_sec: float = Field(default=10.0, ge=0, le=10_000_000)
    latency_ms_p99: float | None = Field(default=None, ge=0, le=3_600_000)  # None = seconds are fine
    ordering: Literal["none", "per_key", "global"] = "none"
    durability: Literal["best_effort", "durable"] = "durable"
    fanout: Literal["single", "multi_consumer"] = "single"
    replay_needed: bool = False
    delayed_jobs: bool = False
    expected_backlog: int = Field(default=0, ge=0, le=10**12)
    cross_service: bool = False


class QueueAdvice(BaseModel):
    recommended: Backend
    reasons: list[str]
    warnings: list[str]
    upgrade_path: list[str]


_UPGRADE: dict[Backend, list[str]] = {
    "postgres": [
        "Stay on Postgres while the sustained rate is below about 1000 jobs/s and the backlog below about 1 million rows.",
        "Past that, move the hot queue to Redis/Celery (best-effort) or RabbitMQ (durable); enqueue(...) and the handlers stay the same.",
        "Past about 5000 jobs/s, or when several consumers need to replay history, move to Kafka.",
    ],
    "redis_celery": [
        "Keep the work that must not be lost (payments, ledgers) on Postgres jobs; use Redis only for work that can be redone.",
        "If lost jobs become unacceptable, move that queue to RabbitMQ (durable queues, acknowledgements).",
    ],
    "rabbitmq": [
        "Start on Postgres jobs and move a queue to RabbitMQ when routing or cross-service delivery is really needed.",
        "If consumers must replay history or the rate passes about 5000 jobs/s, move to Kafka.",
    ],
    "kafka": [
        "Keep delayed and scheduled jobs on Postgres: a log has no delayed delivery.",
        "Adopt Kafka for the streams that need replay or volume only; small queues can stay on Postgres.",
    ],
}


def advise(req: QueueRequirements) -> QueueAdvice:
    """The recommendation for `req`, with the reasons that decided it and the cautions that apply."""
    reasons: list[str] = []
    warnings: list[str] = []
    rate = req.throughput_per_sec

    choice: Backend = "postgres"
    if req.replay_needed and req.fanout == "multi_consumer":
        choice = "kafka"
        reasons.append("several consumers must replay the same history: that is what a log (Kafka) is for")
    elif rate > KAFKA_THROUGHPUT:
        choice = "kafka"
        reasons.append(f"{rate:g} jobs/s sustained is above {KAFKA_THROUGHPUT:g}: partitions are needed to spread it")
    elif req.expected_backlog > KAFKA_BACKLOG:
        choice = "kafka"
        reasons.append(f"a backlog of {req.expected_backlog:,} is too large for a table: a log holds it cheaply")
    elif req.ordering == "per_key" and rate > POSTGRES_THROUGHPUT:
        choice = "kafka"
        reasons.append(f"ordering per key at {rate:g} jobs/s: partition by key (Kafka)")
    elif req.replay_needed and rate > POSTGRES_THROUGHPUT / 2:
        choice = "kafka"
        reasons.append("replay at this rate: keep the history in a log (Kafka) instead of a growing table")
    elif req.fanout == "multi_consumer":
        choice = "rabbitmq"
        reasons.append("one message for several independent consumers: exchanges and routing (RabbitMQ)")
    elif req.cross_service and rate > CROSS_SERVICE_THROUGHPUT:
        choice = "rabbitmq"
        reasons.append(
            f"delivery between services at {rate:g} jobs/s: a broker keeps services from sharing a database (RabbitMQ)"
        )
    elif req.latency_ms_p99 is not None and req.latency_ms_p99 < LOW_LATENCY_MS:
        if req.durability == "durable":
            choice = "rabbitmq"
            reasons.append(
                f"p99 under {LOW_LATENCY_MS:g} ms that must survive a crash: durable broker queues (RabbitMQ)"
            )
        else:
            choice = "redis_celery"
            reasons.append(f"p99 under {LOW_LATENCY_MS:g} ms and losing a job is acceptable: Redis")
    elif rate > POSTGRES_THROUGHPUT:
        if req.durability == "best_effort":
            choice = "redis_celery"
            reasons.append(
                f"{rate:g} jobs/s is above what one Postgres queue handles ({POSTGRES_THROUGHPUT:g}) and losing a job is acceptable: Redis"
            )
        else:
            choice = "rabbitmq"
            reasons.append(
                f"{rate:g} jobs/s is above what one Postgres queue handles ({POSTGRES_THROUGHPUT:g}) and jobs must not be lost: RabbitMQ"
            )
    else:
        reasons.append("no requirement needs more than the app's own database: Postgres is the default")
        if req.durability == "durable":
            reasons.append("durable by construction: a job is a row that commits with your data")
        reasons.append("enqueue can join your transaction, so a rolled-back write enqueues nothing")
        if req.delayed_jobs:
            reasons.append("delayed jobs are a plain run_at column")

    if choice == "postgres":
        if rate > POSTGRES_THROUGHPUT * 0.7:
            warnings.append(
                f"{rate:g} jobs/s is close to the comfortable limit of one Postgres queue ({POSTGRES_THROUGHPUT:g}/s): "
                "watch queue depth and plan the move"
            )
        if req.expected_backlog > POSTGRES_BACKLOG_WARN:
            warnings.append(
                f"a backlog of {req.expected_backlog:,} rows makes claims slower: keep the table purged and indexed"
            )
        if req.ordering == "global":
            warnings.append("global ordering means one worker at a time per queue: throughput is that of a single worker")
        elif req.ordering == "per_key":
            warnings.append("per-key ordering is not enforced by the queue: serialise on the key in the handler (a row lock)")
        if req.cross_service:
            warnings.append("other services would need access to this database or to an API in front of it")
        if req.latency_ms_p99 is not None and req.latency_ms_p99 < 1000:
            warnings.append(
                f"workers poll (default every second): p99 {req.latency_ms_p99:g} ms needs a shorter JOBS_POLL_INTERVAL_SECONDS"
            )
        if req.durability == "best_effort":
            warnings.append("best-effort was declared, but Postgres jobs are durable anyway: nothing is lost on a crash")
    else:
        if req.delayed_jobs and choice == "kafka":
            warnings.append("Kafka has no delayed delivery: keep delayed and scheduled jobs on Postgres")
        if req.delayed_jobs and choice == "rabbitmq":
            warnings.append("delayed delivery in RabbitMQ needs a plugin or a dead-letter delay queue")
        if choice == "redis_celery":
            warnings.append("Redis can lose jobs on a crash or failover: do not use it for work that must happen")
            if req.ordering != "none":
                warnings.append("Celery does not guarantee order: serialise on the key in the handler")
        if req.ordering == "global" and choice in ("rabbitmq", "kafka"):
            warnings.append("global ordering means one consumer (one partition): it caps throughput")
        if req.ordering == "per_key" and choice == "rabbitmq":
            warnings.append("per-key ordering in RabbitMQ needs a consistent-hash exchange and one consumer per shard")
        if choice == "kafka" and req.fanout == "single" and not req.replay_needed:
            warnings.append("a single consumer without replay rarely justifies Kafka: check the rate estimate")
        if req.durability == "best_effort" and choice in ("rabbitmq", "kafka"):
            warnings.append("best-effort was declared: durable settings cost throughput you may not need")
        warnings.append(
            f"only postgres is implemented in the builder today: {choice} is not available yet, "
            "so a project built now would run on Postgres within the limits above"
        )
    return QueueAdvice(recommended=choice, reasons=reasons, warnings=warnings, upgrade_path=list(_UPGRADE[choice]))
