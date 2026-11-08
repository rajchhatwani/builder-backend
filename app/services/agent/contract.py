"""Shared types of the builder agent (architecture 6.1-6.5). Pure data, no database.

Run model (run_service), tool layer (tools), gates (gates) and approvals (approval_service) all
import ONLY from here, so they can be built and tested apart.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.services.ops.scope import Actor


class PermissionClass(StrEnum):
    R = "R"  # read catalogue, spec, owned files, logs, gate reports
    S = "S"  # spec-draft edits through typed operations
    S_BANG = "S!"  # security-weakening / data-removing spec edit: becomes an approval request (D)
    C = "C"  # code in the custom zone only; G0-G4 run on every write
    C_BANG = "C!"  # dependency request
    X = "X"  # run inside the sandbox
    E = "E"  # external side effect: approval per org policy
    # Class F ("does not exist") has NO member on purpose: there is no tool and no credential.


class Phase(StrEnum):
    plan = "plan"  # R only
    build = "build"  # R + S + C + C! + X
    apply = "apply"  # E through humans only


PHASE_CLASSES: dict[Phase, frozenset[PermissionClass]] = {
    Phase.plan: frozenset({PermissionClass.R}),
    Phase.build: frozenset(
        {
            PermissionClass.R,
            PermissionClass.S,
            PermissionClass.S_BANG,
            PermissionClass.C,
            PermissionClass.C_BANG,
            PermissionClass.X,
        }
    ),
    Phase.apply: frozenset({PermissionClass.R, PermissionClass.E}),
}


class ApprovalKind(StrEnum):
    A = "A"  # plan
    B = "B"  # spec diff (with deterministic risk flags)
    C = "C"  # custom code (diff, gate report, tests)
    D = "D"  # destructive or security-weakening
    E = "E"  # first deploy / infrastructure


@dataclass(frozen=True)
class Plan:
    """The approved plan is a contract: the loop may touch only what it lists."""

    plan_id: uuid.UUID
    entities: frozenset[str] = frozenset()  # entity / block names the run may add or change
    hooks: frozenset[str] = frozenset()  # hook names (custom zone) the run may create or edit
    zones: frozenset[str] = frozenset()  # extra custom-zone path prefixes (rarely used)
    dependencies: frozenset[str] = frozenset()  # normalised package names it may request

    def allows(self, kind: str, name: str) -> bool:
        """kind: 'entity' | 'hook' | 'zone' | 'dependency'."""
        pool = {
            "entity": self.entities,
            "hook": self.hooks,
            "zone": self.zones,
            "dependency": self.dependencies,
        }.get(kind)
        if pool is None:
            return False
        if kind == "zone":
            return any(name == z or name.startswith(z.rstrip("/") + "/") for z in pool)
        return name in pool


@dataclass(frozen=True)
class RuleFailure:
    """Every gate or tool failure returns this to the agent (architecture 6.3)."""

    rule_id: str
    location: str
    expected: str
    actual: str
    hint: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "rule_id": self.rule_id,
            "location": self.location,
            "expected": self.expected,
            "actual": self.actual,
            "hint": self.hint,
        }


@dataclass(frozen=True)
class ApprovalRequest:
    """A tool asks for a human decision instead of acting (S!, E, plan extension, new dependency)."""

    kind: ApprovalKind
    subject: str  # short human sentence
    payload: dict[str, Any] = field(default_factory=dict)  # what exactly would happen


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    failures: tuple[RuleFailure, ...] = ()
    approval: ApprovalRequest | None = None  # run pauses until decided
    needs_plan_extension: tuple[str, str] | None = None  # (kind, name) outside the plan


@dataclass
class ToolContext:
    session: AsyncSession
    settings: Settings
    org_id: uuid.UUID
    project_id: uuid.UUID
    run_id: uuid.UUID
    actor: Actor
    phase: Phase
    plan: Plan | None
    workspace_id: uuid.UUID | None = None
    worktree: str | None = None  # absolute path of the draft git worktree
    # True when this tool call is run AGAIN after a crash (its step was still pending): the effects of
    # the first attempt may already be on disk, so a handler must not lose the approval it owed (S1-008).
    reexecution: bool = False


ToolHandler = Callable[[ToolContext, dict[str, Any]], Awaitable[ToolResult]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    perm: PermissionClass
    handler: ToolHandler


@dataclass(frozen=True)
class StopReason:
    """Why a run stopped (run model); machine-readable, shown to the user."""

    code: str  # budget_steps | budget_cost | budget_wall | repairs_exhausted | loop | cancelled | ...
    detail: str = ""
