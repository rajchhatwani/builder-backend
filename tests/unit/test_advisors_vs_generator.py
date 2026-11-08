"""A-001: the queue and workflow advisors must be honest about what the generator can build.

The advisor may *recommend* a broker the builder cannot generate yet (it says so in a warning), but it must
never present a refused backend as buildable: for every advisor output over its whole input space, the
generator's verdict on the recommended backend must agree with what the advisor claims."""

import copy
import itertools
import json
from pathlib import Path
from typing import Any

from app.core import validation_jobs, validation_workflows
from app.core.spec_models import Spec
from app.core.validation import validate
from app.services import queue_advisor, workflow_advisor
from app.services.queue_advisor import QueueRequirements
from app.services.workflow_advisor import WorkflowNeeds

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"
# The advisor's name for a queue backend -> the value a spec's jobs.queue.backend takes.
SPEC_BACKEND = {"postgres": "postgres", "redis_celery": "redis", "rabbitmq": "rabbitmq", "kafka": "kafka"}


def _verdict_on_backend(backend: str) -> str:
    data: dict[str, Any] = copy.deepcopy(json.loads((FIXTURES / "jobs_invoices.json").read_text(encoding="utf-8")))
    data["jobs"]["queue"]["backend"] = backend
    hits = [i.code for i in validate(Spec.model_validate(data)) if i.path == "jobs.queue.backend"]
    return hits[0] if hits else "accepted"


def _queue_grid() -> list[QueueRequirements]:
    rows = []
    for rate, lat, order, dur, fan, replay, delayed, backlog, cross in itertools.product(
        (0, 10, 300, 900, 1500, 3000, 20_000),
        (None, 1.0, 10.0, 500.0),
        ("none", "per_key", "global"),
        ("best_effort", "durable"),
        ("single", "multi_consumer"),
        (False, True),
        (False, True),
        (0, 2_000_000, 80_000_000),
        (False, True),
    ):
        rows.append(
            QueueRequirements(
                throughput_per_sec=rate, latency_ms_p99=lat, ordering=order, durability=dur, fanout=fan,
                replay_needed=replay, delayed_jobs=delayed, expected_backlog=backlog, cross_service=cross,
            )
        )
    return rows


def test_the_advisor_backends_match_what_the_generator_knows() -> None:
    advisor_backends = set(queue_advisor.Backend.__args__)  # type: ignore[attr-defined]
    assert advisor_backends == set(SPEC_BACKEND)  # a new advisor backend must be mapped here
    for adv, spec_value in SPEC_BACKEND.items():
        verdict = _verdict_on_backend(spec_value)
        if adv in queue_advisor.IMPLEMENTED:
            assert verdict == "accepted", f"{adv} is claimed implemented but the generator says {verdict}"
        else:
            assert verdict in ("not_yet_implemented", "unknown_backend"), (
                f"{adv} is claimed NOT implemented but the generator accepts it"
            )
    # and the generator's own refusal list is exactly what the advisor does not implement
    assert set(validation_jobs.BACKENDS) - set(validation_jobs.NOT_YET_IMPLEMENTED) == {
        SPEC_BACKEND[b] for b in queue_advisor.IMPLEMENTED
    }


def test_every_queue_advice_is_honest_about_what_can_be_built() -> None:
    seen: set[str] = set()
    for req in _queue_grid():
        advice = queue_advisor.advise(req)
        seen.add(advice.recommended)
        buildable = _VERDICT[advice.recommended] == "accepted"
        said_unavailable = any("not available yet" in w and advice.recommended in w for w in advice.warnings)
        if buildable:
            assert not said_unavailable, req
        else:
            # a refused backend is only ever recommended together with an explicit "not available" warning
            assert said_unavailable, (advice.recommended, req)
    assert seen == set(SPEC_BACKEND)  # the grid reaches every advisor output


_VERDICT = {adv: _verdict_on_backend(spec) for adv, spec in SPEC_BACKEND.items()}


def test_workflow_advice_is_always_buildable() -> None:
    assert set(validation_workflows.RUNTIMES) - set(validation_workflows.NOT_YET_IMPLEMENTED) == {"postgres"}
    seen = set()
    for steps, comp, wait, longest, fire, status, systems in itertools.product(
        (1, 2, 3, 31), (False, True), (False, True), (1.0, 3600.0), (False, True), (False, True), (0, 1, 2)
    ):
        advice = workflow_advisor.advise(
            WorkflowNeeds(steps=steps, needs_compensation=comp, human_wait=wait, longest_step_seconds=longest,
                          fire_and_forget=fire, status_only=status, outside_systems=systems)
        )
        seen.add(advice.recommended)
        # `workflow` runs on the Postgres runner only; the advice must say implemented and never name dbos/temporal
        assert advice.implemented is True
        text = " ".join([advice.next_step, *advice.reasons, *advice.warnings]).lower()
        assert "dbos" not in text and "temporal" not in text
    assert seen == {"queue", "state_machine", "workflow"}
