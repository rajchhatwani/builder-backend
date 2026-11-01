"""Schemas for the behaviour of a project (state machines). Shapes and sizes are checked here;
whether names, states, roles and guard expressions are legal is `validation.validate`'s job, so
the dashboard can save work in progress and read every problem.

Versioning contract (additive, backward compatible): each section (`state_machines`, `settings`,
`sequences`, `lists`, `history`, `hooks`, `seed`) has its OWN `version`. A GET returns that
section's `version` (0 = never saved). A PUT carrying `expected_version` is refused with
409 `conflict` only when THAT section changed since it was read; saves to other sections never
make it stale. Omitting `expected_version` overwrites without a check. The `row_version` of a
Read is the old whole-row counter, kept for old clients and not used for conflict checks."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TransitionBody(BaseModel):
    name: str = Field(max_length=80)
    from_states: list[str] = Field(default_factory=list, max_length=100)
    to_state: str = Field(max_length=80)
    when: str | None = Field(default=None, max_length=5000)
    roles: list[str] = Field(default_factory=list, max_length=50)
    auto: bool = False


class StateMachineBody(BaseModel):
    entity: str = Field(max_length=80)
    field: str = Field(max_length=80)
    initial: str = Field(max_length=80)
    transitions: list[TransitionBody] = Field(default_factory=list, max_length=500)


class StateMachinesWrite(BaseModel):
    """Body of PUT /projects/{id}/behavior/state-machines. Replaces every machine."""

    state_machines: list[StateMachineBody] = Field(default_factory=list, max_length=200)
    expected_version: int | None = Field(default=None, ge=0)


class StateMachinesRead(BaseModel):
    project_id: uuid.UUID
    version: int  # 0 = never saved
    updated_at: datetime | None = None
    row_version: int = 0  # whole-row counter, informational only (see module docstring)
    state_machines: list[StateMachineBody]


class SettingBody(BaseModel):
    key: str = Field(max_length=80)
    type: str = Field(default="string", max_length=20)
    default: str | int | bool | None = None
    label: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    minimum: str | int | None = None
    maximum: str | int | None = None
    max_length: int | None = Field(default=None, ge=0, le=100000)
    read_roles: list[str] = Field(default_factory=list, max_length=50)
    edit_roles: list[str] = Field(default_factory=list, max_length=50)


class SettingsWrite(BaseModel):
    """Body of PUT /projects/{id}/behavior/settings. Replaces every setting."""

    settings: list[SettingBody] = Field(default_factory=list, max_length=500)
    expected_version: int | None = Field(default=None, ge=0)


class SettingsRead(BaseModel):
    project_id: uuid.UUID
    version: int  # 0 = never saved
    updated_at: datetime | None = None
    row_version: int = 0  # whole-row counter, informational only (see module docstring)
    settings: list[SettingBody]


class SequenceBody(BaseModel):
    name: str = Field(max_length=80)
    prefix: str = Field(default="", max_length=40)
    padding: int = Field(default=0, ge=0, le=100)
    start: int = Field(default=1, ge=0, le=2**62)
    per_tenant: bool = False
    reset_yearly: bool = False
    view_roles: list[str] = Field(default_factory=list, max_length=50)
    entity: str | None = Field(default=None, max_length=80)
    field: str | None = Field(default=None, max_length=80)


class SequencesWrite(BaseModel):
    """Body of PUT /projects/{id}/behavior/sequences. Replaces every sequence."""

    sequences: list[SequenceBody] = Field(default_factory=list, max_length=200)
    expected_version: int | None = Field(default=None, ge=0)


class SequencesRead(BaseModel):
    project_id: uuid.UUID
    version: int
    updated_at: datetime | None = None
    row_version: int = 0  # whole-row counter, informational only (see module docstring)
    sequences: list[SequenceBody]


class ListItemBody(BaseModel):
    value: str = Field(max_length=80)
    label: str = Field(max_length=200)
    color: str | None = Field(default=None, max_length=20)
    locked: bool = False


class ListBody(BaseModel):
    name: str = Field(max_length=80)
    label: str | None = Field(default=None, max_length=120)
    items: list[ListItemBody] = Field(default_factory=list, max_length=1000)
    max_items: int = Field(default=100, ge=0, le=100000)
    edit_roles: list[str] = Field(default_factory=list, max_length=50)


class ListsWrite(BaseModel):
    """Body of PUT /projects/{id}/behavior/lists. Replaces every list."""

    lists: list[ListBody] = Field(default_factory=list, max_length=500)
    expected_version: int | None = Field(default=None, ge=0)


class ListsRead(BaseModel):
    project_id: uuid.UUID
    version: int
    updated_at: datetime | None = None
    row_version: int = 0  # whole-row counter, informational only (see module docstring)
    lists: list[ListBody]


class HistoryBody(BaseModel):
    entity: str = Field(max_length=80)
    fields: list[str] = Field(default_factory=list, max_length=200)
    retention_days: int = Field(
        ge=-1_000_000, le=1_000_000
    )  # the range 1..3650 is checked by validation
    view_roles: list[str] = Field(default_factory=list, max_length=50)


class HistoryWrite(BaseModel):
    """Body of PUT /projects/{id}/behavior/history. Replaces every change-history config."""

    history: list[HistoryBody] = Field(default_factory=list, max_length=200)
    expected_version: int | None = Field(default=None, ge=0)


class HistoryRead(BaseModel):
    project_id: uuid.UUID
    version: int
    updated_at: datetime | None = None
    row_version: int = 0  # whole-row counter, informational only (see module docstring)
    history: list[HistoryBody]


class HookFieldBody(BaseModel):
    name: str = Field(max_length=80)
    type: str = Field(default="string", max_length=20)
    required: bool = True


class HookModelBody(BaseModel):
    name: str = Field(max_length=80)
    fields: list[HookFieldBody] = Field(
        default_factory=list, max_length=200
    )  # validation caps at 30


class HookBudgetBody(BaseModel):
    cpu_ms: int = Field(
        default=200, ge=-1_000_000, le=1_000_000
    )  # ceilings are checked by validation
    rows: int = Field(default=0, ge=-1_000_000, le=1_000_000)
    outbound_calls: int = Field(default=0, ge=-1_000_000, le=1_000_000)


class HookBody(BaseModel):
    name: str = Field(max_length=80)
    point: str = Field(max_length=200)
    kind: str = Field(default="pure", max_length=20)
    input: HookModelBody
    output: HookModelBody
    failure_policy: str | None = Field(default=None, max_length=20)
    fallback: dict[str, str | int | float | bool] | None = Field(default=None, max_length=60)
    budget: HookBudgetBody = Field(default_factory=HookBudgetBody)
    reads: list[str] = Field(default_factory=list, max_length=50)


class HooksWrite(BaseModel):
    """Body of PUT /projects/{id}/behavior/hooks. Replaces every hook declaration."""

    hooks: list[HookBody] = Field(default_factory=list, max_length=200)
    expected_version: int | None = Field(default=None, ge=0)


class HooksRead(BaseModel):
    project_id: uuid.UUID
    version: int
    updated_at: datetime | None = None
    row_version: int = 0  # whole-row counter, informational only (see module docstring)
    hooks: list[HookBody]


class _SeedBody(BaseModel):
    model_config = {"extra": "forbid"}  # a seed plan accepts nothing outside its schema


class SeedGeneratorBody(_SeedBody):
    """One generator of a seed plan. Shapes and sizes only; which keys a type takes and whether the values
    fit the column is `validation.validate`'s job."""

    type: str = Field(max_length=30)
    value: str | int | float | bool | None = Field(default=None)
    values: list[str | int | float | bool] | None = Field(default=None, max_length=1000)
    prefix: str | None = Field(default=None, max_length=100)
    start: int | None = Field(default=None, ge=-(2**62), le=2**62)
    width: int | None = Field(default=None, ge=-1000, le=1000)
    min: str | int | None = None
    max: str | int | None = None
    places: int | None = Field(default=None, ge=-1000, le=1000)
    ratio: float | None = Field(default=None, ge=-1000, le=1000)
    min_words: int | None = Field(default=None, ge=-1000, le=1000)
    max_words: int | None = Field(default=None, ge=-1000, le=1000)
    entity: str | None = Field(default=None, max_length=80)
    pick: str | None = Field(default=None, max_length=20)
    weights: dict[str, int] | None = Field(default=None, max_length=200)


class SeedFieldBody(_SeedBody):
    field: str = Field(max_length=80)
    generator: SeedGeneratorBody


class SeedEntityBody(_SeedBody):
    entity: str = Field(max_length=80)
    count: int = Field(ge=-1_000_000, le=1_000_000)  # the ceiling is checked by validation
    fields: list[SeedFieldBody] = Field(default_factory=list, max_length=300)


class SeedProfileBody(_SeedBody):
    name: str = Field(max_length=40)
    seed: int = Field(ge=-(2**62), le=2**62)
    as_of: str = Field(max_length=20)
    tenants: int = Field(default=0, ge=-1000, le=1000)
    entities: list[SeedEntityBody] = Field(default_factory=list, max_length=200)


class SeedWrite(_SeedBody):
    """Body of PUT /projects/{id}/behavior/seed. Replaces every seed profile."""

    seed: list[SeedProfileBody] = Field(default_factory=list, max_length=20)
    expected_version: int | None = Field(default=None, ge=0)


class SeedRead(BaseModel):
    project_id: uuid.UUID
    version: int
    updated_at: datetime | None = None
    row_version: int = 0  # whole-row counter, informational only (see module docstring)
    seed: list[SeedProfileBody]


class RoleOption(BaseModel):
    name: str
    label: str


class RolesRead(BaseModel):
    """GET /projects/{id}/behavior/roles: the role names declared by the project's auth config, for
    the role pickers of the behaviour pages. Empty when sign-in has no roles (or is not set up).
    Readable by anyone who can read the project spec; carries names and labels only."""

    project_id: uuid.UUID
    roles: list[RoleOption]


class BehaviorIssues(BaseModel):
    issues: list[dict[str, str]]


class ExpressionCheckBody(BaseModel):
    """Body of POST /projects/{id}/behavior/expressions/check (no side effects)."""

    entity: str = Field(max_length=80)
    expression: str = Field(max_length=1000)
    expect: Literal["bool", "any"] = "bool"


class ExpressionError(BaseModel):
    message: str  # exactly the message the validation report gives for the same expression
    pos: int


class ExpressionField(BaseModel):
    name: str
    type: str  # string | int | decimal | bool
    nullable: bool


class ExpressionCheckRead(BaseModel):
    ok: bool
    type: str | None = None
    error: ExpressionError | None = None
    fields: list[ExpressionField]


# --- single-object blocks (B2-11): events, providers, notifications, jobs, workflows, api_edge,
# webhooks, hook_effects. The body IS the spec block, so a block saved here and one saved with
# PUT /spec are byte-identical. `null` removes the block. Same per-section version contract.
from app.core.spec_models import (  # noqa: E402
    SpecApiEdge,
    SpecEvents,
    SpecHookEffects,
    SpecJobs,
    SpecNotifications,
    SpecProviders,
    SpecWebhooks,
    SpecWorkflows,
)


class _BlockRead(BaseModel):
    project_id: uuid.UUID
    version: int  # 0 = never saved
    updated_at: datetime | None = None
    row_version: int = 0


class _BlockWrite(BaseModel):
    model_config = {"extra": "forbid"}
    expected_version: int | None = Field(default=None, ge=0)


class EventsWrite(_BlockWrite):
    events: SpecEvents | None = None


class EventsRead(_BlockRead):
    events: SpecEvents | None = None


class ProvidersWrite(_BlockWrite):
    providers: SpecProviders | None = None


class ProvidersRead(_BlockRead):
    providers: SpecProviders | None = None


class NotificationsWrite(_BlockWrite):
    notifications: SpecNotifications | None = None


class NotificationsRead(_BlockRead):
    notifications: SpecNotifications | None = None


class JobsWrite(_BlockWrite):
    jobs: SpecJobs | None = None


class JobsRead(_BlockRead):
    jobs: SpecJobs | None = None


class WorkflowsWrite(_BlockWrite):
    workflows: SpecWorkflows | None = None


class WorkflowsRead(_BlockRead):
    workflows: SpecWorkflows | None = None


class ApiEdgeWrite(_BlockWrite):
    api_edge: SpecApiEdge | None = None


class ApiEdgeRead(_BlockRead):
    api_edge: SpecApiEdge | None = None


class WebhooksWrite(_BlockWrite):
    webhooks: SpecWebhooks | None = None


class WebhooksRead(_BlockRead):
    webhooks: SpecWebhooks | None = None


class HookEffectsWrite(_BlockWrite):
    hook_effects: SpecHookEffects | None = None


class HookEffectsRead(_BlockRead):
    hook_effects: SpecHookEffects | None = None
