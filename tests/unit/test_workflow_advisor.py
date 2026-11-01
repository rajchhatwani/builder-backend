"""Workflow advisor: a table of declared needs -> queue, state machine or workflow, with reasons."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.services.workflow_advisor import LONG_RUNNING_SECONDS, WorkflowNeeds, advise

ROWS: list[tuple[str, dict[str, Any], str]] = [
    ("defaults_are_one_unit_of_work", {}, "queue"),
    ("fire_and_forget_email", {"fire_and_forget": True}, "queue"),
    ("single_long_step", {"longest_step_seconds": 7200}, "queue"),
    ("single_step_with_cleanup", {"needs_compensation": True}, "queue"),
    ("chained_jobs_no_undo", {"steps": 3}, "queue"),
    ("status_lifecycle", {"status_only": True}, "state_machine"),
    ("status_lifecycle_with_approver", {"status_only": True, "human_wait": True}, "state_machine"),
    ("one_approval_wait", {"human_wait": True}, "state_machine"),
    ("saga_two_steps", {"steps": 2, "needs_compensation": True}, "workflow"),
    ("saga_beats_status", {"steps": 3, "needs_compensation": True, "status_only": True}, "workflow"),
    ("approval_between_steps", {"steps": 2, "human_wait": True}, "workflow"),
    ("long_multi_step", {"steps": 2, "longest_step_seconds": LONG_RUNNING_SECONDS + 1}, "workflow"),
    ("exactly_the_long_limit_is_not_long", {"steps": 2, "longest_step_seconds": LONG_RUNNING_SECONDS}, "queue"),
    ("three_steps_two_systems", {"steps": 3, "outside_systems": 2}, "workflow"),
    ("three_steps_one_system", {"steps": 3, "outside_systems": 1}, "queue"),
    ("two_steps_two_systems_no_undo", {"steps": 2, "outside_systems": 2}, "queue"),
    ("fire_and_forget_with_many_steps_still_chains", {"steps": 2, "fire_and_forget": True}, "queue"),
]


@pytest.mark.parametrize(("name", "needs", "expected"), ROWS, ids=[r[0] for r in ROWS])
def test_the_recommendation(name: str, needs: dict[str, Any], expected: str) -> None:
    advice = advise(WorkflowNeeds(**needs))
    assert advice.recommended == expected, (name, advice.reasons)
    assert advice.reasons and advice.next_step


def test_a_single_wait_warns_about_reminders() -> None:
    assert any("scheduled job" in w for w in advise(WorkflowNeeds(human_wait=True)).warnings)


def test_chained_jobs_warn_about_growth() -> None:
    assert any("move to a workflow" in w for w in advise(WorkflowNeeds(steps=3)).warnings)


def test_the_advice_is_deterministic() -> None:
    needs = WorkflowNeeds(steps=4, needs_compensation=True)
    assert advise(needs) == advise(needs)


@pytest.mark.parametrize("bad", [{"steps": 0}, {"longest_step_seconds": -1}, {"outside_systems": -1}, {"surprise": 1}])
def test_bad_needs_are_refused(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        WorkflowNeeds(**bad)
