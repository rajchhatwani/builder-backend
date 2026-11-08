"""Validation for the `workflows` section (durable sagas, C12). Issues go through `add(path, code, message)`.
Nothing here runs anything: it checks shape, ranges and supported values, and fails closed."""

import re
from collections.abc import Callable

from app.core.spec_models import Spec

Add = Callable[[str, str, str], None]

WORKFLOW_TABLES = ("wf_runs", "wf_steps")
RUNTIMES = ("postgres", "dbos", "temporal")
# Accepted by the schema, no working implementation yet.
NOT_YET_IMPLEMENTED = ("dbos", "temporal")
KINDS = ("hook", "job")
ON_FAILURE = ("compensate", "fail")
BACKOFFS = ("exponential", "fixed")

NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")

MAX_WORKFLOWS = 50
MAX_STEPS = 30
CONCURRENCY = (1, 64)
ATTEMPTS = (1, 20)
BACKOFF_SECONDS = (1, 86_400)
STEP_TIMEOUT = (1, 21_600)
WORKFLOW_TIMEOUT = (1, 30 * 86_400)


def workflows_active(spec: Spec) -> bool:
    return spec.workflows is not None and spec.workflows.enabled


def _in_range(value: object, bounds: tuple[int, int]) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and bounds[0] <= value <= bounds[1]


def check_workflows(spec: Spec, add: Add) -> None:
    cfg = spec.workflows
    if cfg is None or not cfg.enabled:
        return
    if cfg.runtime not in RUNTIMES:
        add("workflows.runtime", "unknown_runtime", f"runtime must be one of: {', '.join(RUNTIMES)}")
    elif cfg.runtime in NOT_YET_IMPLEMENTED:
        add(
            "workflows.runtime",
            "not_yet_implemented",
            f"the {cfg.runtime} runtime is not implemented yet: use postgres "
            "(the built-in durable runner; the runner interface is kept narrow so an engine can be added later)",
        )
    if spec.auth is None or not spec.auth.enabled:
        add("workflows", "needs_auth", "workflow runs are started and read through an authenticated API: enable auth first")
    if not _in_range(cfg.worker.concurrency, CONCURRENCY):
        add("workflows.worker.concurrency", "invalid_value", f"concurrency must be {CONCURRENCY[0]} to {CONCURRENCY[1]}")
    if not cfg.workflows:
        add("workflows.workflows", "no_workflows", "declare at least one workflow")
    if len(cfg.workflows) > MAX_WORKFLOWS:
        add("workflows.workflows", "too_many", f"at most {MAX_WORKFLOWS} workflows")

    auth_roles = {r.name for r in spec.auth.roles} if spec.auth is not None and spec.auth.enabled else set()
    job_names = {j.name for j in spec.jobs.jobs} if spec.jobs is not None and spec.jobs.enabled else set()
    names: set[str] = set()
    for i, wf in enumerate(cfg.workflows):
        path = f"workflows.workflows[{i}]"
        if not NAME_RE.fullmatch(wf.name):
            add(f"{path}.name", "invalid_name", "a workflow name is lower-case letters, digits and _, starting with a letter (40 at most)")
        elif wf.name in names:
            add(f"{path}.name", "duplicate_name", f"workflow {wf.name!r} is declared twice")
        names.add(wf.name)
        if wf.on_failure not in ON_FAILURE:
            add(f"{path}.on_failure", "invalid_value", f"on_failure must be one of: {', '.join(ON_FAILURE)}")
        if not _in_range(wf.timeout_seconds, WORKFLOW_TIMEOUT):
            add(f"{path}.timeout_seconds", "invalid_value", f"timeout_seconds must be {WORKFLOW_TIMEOUT[0]} to {WORKFLOW_TIMEOUT[1]}")
        if not wf.roles:
            add(f"{path}.roles", "no_roles", "name at least one role that may start, read and cancel runs (default deny)")
        for role in wf.roles:
            if role not in auth_roles:
                add(f"{path}.roles", "unknown_role", f"role {role!r} is not declared in auth.roles")
        if not wf.steps:
            add(f"{path}.steps", "no_steps", "a workflow needs at least one step")
        if len(wf.steps) > MAX_STEPS:
            add(f"{path}.steps", "too_many", f"at most {MAX_STEPS} steps")
        step_names: set[str] = set()
        for j, st in enumerate(wf.steps):
            sp = f"{path}.steps[{j}]"
            if not NAME_RE.fullmatch(st.name):
                add(f"{sp}.name", "invalid_name", "a step name is lower-case letters, digits and _, starting with a letter (40 at most)")
            elif st.name in step_names:
                add(f"{sp}.name", "duplicate_name", f"step {st.name!r} is declared twice in workflow {wf.name!r}")
            step_names.add(st.name)
            if st.kind not in KINDS:
                add(f"{sp}.kind", "invalid_value", f"kind must be one of: {', '.join(KINDS)}")
            elif st.kind == "job":
                if st.job is None:
                    add(f"{sp}.job", "missing_job", "a job step names the job it enqueues")
                elif not job_names:
                    add(f"{sp}.job", "needs_jobs", "a job step needs the jobs block enabled")
                elif st.job not in job_names:
                    add(f"{sp}.job", "unknown_job", f"job {st.job!r} is not declared")
            elif st.job is not None:
                add(f"{sp}.job", "unexpected_job", "only a job step names a job")
            if not _in_range(st.timeout_seconds, STEP_TIMEOUT):
                add(f"{sp}.timeout_seconds", "invalid_value", f"timeout_seconds must be {STEP_TIMEOUT[0]} to {STEP_TIMEOUT[1]}")
            if not _in_range(st.retry.max_attempts, ATTEMPTS):
                add(f"{sp}.retry.max_attempts", "invalid_value", f"max_attempts must be {ATTEMPTS[0]} to {ATTEMPTS[1]}")
            if not _in_range(st.retry.backoff_seconds, BACKOFF_SECONDS):
                add(f"{sp}.retry.backoff_seconds", "invalid_value", f"backoff_seconds must be {BACKOFF_SECONDS[0]} to {BACKOFF_SECONDS[1]}")
            if st.retry.backoff not in BACKOFFS:
                add(f"{sp}.retry.backoff", "invalid_value", f"backoff must be one of: {', '.join(BACKOFFS)}")
        if wf.on_failure == "compensate" and wf.steps and not any(s.compensate for s in wf.steps):
            add(f"{path}.on_failure", "nothing_to_compensate", "on_failure is compensate but no step has a compensation: use fail, or mark a step compensate")
