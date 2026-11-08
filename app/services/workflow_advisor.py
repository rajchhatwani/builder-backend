"""Workflow advisor: queue, state machine or durable workflow, from the declared need. A pure function.

The rules run in this order and the first that matches decides, so every answer can be explained by the
reasons it returns:

  1. workflow      two or more steps where an earlier step must be undone when a later one fails (saga)
  2. workflow      two or more steps with a human wait between them (approvals, long waits)
  3. workflow      two or more steps that run for a long time (a restart must not lose the progress)
  4. workflow      three or more steps across several outside systems (each needs retries and an audit trail)
  5. state_machine the entity only moves between allowed states (a status lifecycle, optionally waiting for a
                   person) and nothing has to be orchestrated between the states
  6. state_machine a single human wait with no other work
  7. queue         fire-and-forget or one unit of work (retries and a schedule come with the queue)
  8. queue         several steps with no undo, no waits and nothing long: chain jobs (warning given)

`workflow` is only built-in as the Postgres runner; dbos and temporal are not implemented yet.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Kind = Literal["queue", "state_machine", "workflow"]

LONG_RUNNING_SECONDS = 15 * 60  # a step longer than this is "long running"
MANY_STEPS_ACROSS_SYSTEMS = 3


class WorkflowNeeds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: int = Field(default=1, ge=1, le=1000)
    needs_compensation: bool = False  # an earlier step must be undone when a later one fails
    human_wait: bool = False  # a person must act (approve, upload, confirm) before the work continues
    longest_step_seconds: float = Field(default=1.0, ge=0, le=10**9)
    fire_and_forget: bool = False  # nobody waits for the result and nothing depends on it
    status_only: bool = False  # the need is "this record is in state X; only some moves are allowed"
    outside_systems: int = Field(default=0, ge=0, le=1000)  # distinct external systems the steps call


class WorkflowAdvice(BaseModel):
    recommended: Kind
    reasons: list[str]
    warnings: list[str]
    implemented: bool
    next_step: str


_NEXT: dict[Kind, str] = {
    "queue": "Declare a job in the `jobs` block and enqueue it from your code.",
    "state_machine": "Declare a state machine on the entity in the `state_machines` section.",
    "workflow": "Declare a workflow with ordered steps and their compensations in the `workflows` block.",
}


def advise(needs: WorkflowNeeds) -> WorkflowAdvice:
    reasons: list[str] = []
    warnings: list[str] = []
    long_running = needs.longest_step_seconds > LONG_RUNNING_SECONDS
    multi = needs.steps >= 2
    choice: Kind

    if multi and needs.needs_compensation:
        choice = "workflow"
        reasons.append("an earlier step must be undone when a later one fails: that is a saga, with compensations in reverse order")
    elif multi and needs.human_wait:
        choice = "workflow"
        reasons.append("the work waits for a person between steps: progress must be kept durably until they act")
    elif multi and long_running:
        choice = "workflow"
        reasons.append(
            f"a step runs longer than {LONG_RUNNING_SECONDS // 60} minutes across several steps: a restart must resume, not start over"
        )
    elif needs.steps >= MANY_STEPS_ACROSS_SYSTEMS and needs.outside_systems >= 2:
        choice = "workflow"
        reasons.append("several steps across outside systems: each needs its own retries and a record of how far it got")
    elif needs.status_only and not multi:
        choice = "state_machine"
        reasons.append("the need is a status lifecycle with allowed moves: a state machine states and enforces it")
        if needs.human_wait:
            reasons.append("who may make each move is a transition role, so a person's decision is just a transition")
    elif needs.human_wait and not multi:
        choice = "state_machine"
        reasons.append("one wait for a person and no other work: a state (waiting) and a transition (approved) are enough")
        warnings.append("reminders and timeouts on the wait need a scheduled job on top of the state machine")
    elif needs.fire_and_forget or needs.steps == 1:
        choice = "queue"
        reasons.append("one unit of work nobody waits on: a job gets retries, backoff and a dead-letter list")
        if long_running:
            warnings.append("a single long step: raise the job's timeout and make it idempotent; split it if it can be resumed in parts")
        if needs.needs_compensation:
            warnings.append("there is nothing earlier to undo in a single step: put the cleanup in the handler")
    else:
        choice = "queue"
        reasons.append("several steps with no undo, no waits and nothing long: chained jobs are enough")
        warnings.append("if a later step ever needs the earlier ones undone, or a step starts to wait for a person, move to a workflow")

    if choice == "workflow":
        if needs.status_only:
            warnings.append("the entity's own status can still be a state machine; the workflow drives the work between its states")
        if needs.steps > 30:
            warnings.append("a workflow has at most 30 steps: group steps or split the process")
    return WorkflowAdvice(
        recommended=choice, reasons=reasons, warnings=warnings, implemented=True, next_step=_NEXT[choice]
    )
