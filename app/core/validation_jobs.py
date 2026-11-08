"""Validation for the `jobs` section (background jobs, schedules, worker groups). Issues go through
`add(path, code, message)`. Nothing here runs anything: it checks shape, ranges and supported values."""

import keyword
import re
from collections.abc import Callable

from app.core import jobs_cron
from app.core.spec_models import Spec

Add = Callable[[str, str, str], None]

JOB_TABLES = ("jb_jobs", "jb_schedule_fires", "jb_schedules")
BACKENDS = ("postgres", "redis", "rabbitmq")
# Accepted by the schema, no working implementation yet.
NOT_YET_IMPLEMENTED = ("redis", "rabbitmq")
PLACEMENTS = ("same_server", "separate_server")
BACKOFFS = ("exponential", "fixed")
MISSED = ("skip", "catch_up_one")

NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")
GROUP_RE = re.compile(r"[a-z][a-z0-9_]{0,29}")
HANDLER_RE = re.compile(r"[a-z_][a-z0-9_]{0,59}")

MAX_JOBS = 100
MAX_GROUPS = 20
MAX_SCHEDULES = 50
CONCURRENCY = (1, 64)
ATTEMPTS = (1, 50)
BACKOFF_SECONDS = (1, 86_400)
TIMEOUT_SECONDS = (1, 21_600)


def jobs_active(spec: Spec) -> bool:
    return spec.jobs is not None and spec.jobs.enabled


def _in_range(value: object, bounds: tuple[int, int]) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and bounds[0] <= value <= bounds[1]


def check_jobs(spec: Spec, add: Add) -> None:
    cfg = spec.jobs
    if cfg is None or not cfg.enabled:
        return
    backend = cfg.queue.backend
    if backend not in BACKENDS:
        add("jobs.queue.backend", "unknown_backend", f"backend must be one of: {', '.join(BACKENDS)}")
    elif backend in NOT_YET_IMPLEMENTED:
        add(
            "jobs.queue.backend",
            "not_yet_implemented",
            f"the {backend} queue is not implemented yet: use postgres "
            "(the queue interface is kept narrow so a broker can be added later)",
        )
    if len(cfg.jobs) > MAX_JOBS:
        add("jobs.jobs", "too_many", f"at most {MAX_JOBS} jobs")
    if len(cfg.worker_groups) > MAX_GROUPS:
        add("jobs.worker_groups", "too_many", f"at most {MAX_GROUPS} worker groups")
    if len(cfg.schedules) > MAX_SCHEDULES:
        add("jobs.schedules", "too_many", f"at most {MAX_SCHEDULES} schedules")
    if not cfg.jobs:
        add("jobs.jobs", "no_jobs", "declare at least one job")

    names: set[str] = set()
    job_queues: set[str] = set()
    for i, job in enumerate(cfg.jobs):
        path = f"jobs.jobs[{i}]"
        if not NAME_RE.fullmatch(job.name):
            add(f"{path}.name", "invalid_name", "a job name is lower-case letters, digits and _, starting with a letter (40 at most)")
        elif job.name in names:
            add(f"{path}.name", "duplicate_name", f"job {job.name!r} is declared twice")
        names.add(job.name)
        if not NAME_RE.fullmatch(job.queue):
            add(f"{path}.queue", "invalid_name", "a queue name is lower-case letters, digits and _, starting with a letter")
        job_queues.add(job.queue)
        if not HANDLER_RE.fullmatch(job.handler) or keyword.iskeyword(job.handler):
            add(f"{path}.handler", "invalid_handler", "handler must be a plain Python function name (written in app/hooks/jobs.py)")
        if not _in_range(job.timeout_seconds, TIMEOUT_SECONDS):
            add(f"{path}.timeout_seconds", "invalid_value", f"timeout_seconds must be {TIMEOUT_SECONDS[0]} to {TIMEOUT_SECONDS[1]}")
        if not _in_range(job.retry.max_attempts, ATTEMPTS):
            add(f"{path}.retry.max_attempts", "invalid_value", f"max_attempts must be {ATTEMPTS[0]} to {ATTEMPTS[1]}")
        if not _in_range(job.retry.backoff_seconds, BACKOFF_SECONDS):
            add(f"{path}.retry.backoff_seconds", "invalid_value", f"backoff_seconds must be {BACKOFF_SECONDS[0]} to {BACKOFF_SECONDS[1]}")
        if job.retry.backoff not in BACKOFFS:
            add(f"{path}.retry.backoff", "invalid_value", f"backoff must be one of: {', '.join(BACKOFFS)}")

    handlers = [j.handler for j in cfg.jobs]
    for handler in sorted({h for h in handlers if handlers.count(h) > 1}):
        add("jobs.jobs", "duplicate_handler", f"handler {handler!r} is used by more than one job")

    group_names: set[str] = set()
    served: set[str] = set()
    for i, group in enumerate(cfg.worker_groups):
        path = f"jobs.worker_groups[{i}]"
        if not GROUP_RE.fullmatch(group.name):
            add(f"{path}.name", "invalid_name", "a group name is lower-case letters, digits and _, starting with a letter (30 at most)")
        elif group.name in group_names:
            add(f"{path}.name", "duplicate_name", f"worker group {group.name!r} is declared twice")
        group_names.add(group.name)
        if not _in_range(group.concurrency, CONCURRENCY):
            add(f"{path}.concurrency", "invalid_value", f"concurrency must be {CONCURRENCY[0]} to {CONCURRENCY[1]}")
        if group.placement not in PLACEMENTS:
            add(f"{path}.placement", "invalid_value", f"placement must be one of: {', '.join(PLACEMENTS)}")
        if not group.queues:
            add(f"{path}.queues", "no_queues", "a worker group needs at least one queue")
        for queue in group.queues:
            if queue not in job_queues:
                add(f"{path}.queues", "unknown_queue", f"queue {queue!r} has no job")
            served.add(queue)
    for queue in sorted(job_queues - served):
        add("jobs.worker_groups", "queue_without_worker", f"no worker group serves queue {queue!r}: its jobs would never run")

    schedule_names: set[str] = set()
    for i, sched in enumerate(cfg.schedules):
        path = f"jobs.schedules[{i}]"
        if not NAME_RE.fullmatch(sched.name):
            add(f"{path}.name", "invalid_name", "a schedule name is lower-case letters, digits and _, starting with a letter")
        elif sched.name in schedule_names:
            add(f"{path}.name", "duplicate_name", f"schedule {sched.name!r} is declared twice")
        schedule_names.add(sched.name)
        if sched.job not in names:
            add(f"{path}.job", "unknown_job", f"job {sched.job!r} is not declared")
        if sched.missed not in MISSED:
            add(f"{path}.missed", "invalid_value", f"missed must be one of: {', '.join(MISSED)}")
        try:
            jobs_cron.validate(sched.cron, sched.timezone)
        except jobs_cron.CronError as exc:
            code = "invalid_timezone" if "timezone" in str(exc) else "invalid_cron"
            add(f"{path}.cron" if code == "invalid_cron" else f"{path}.timezone", code, str(exc))
