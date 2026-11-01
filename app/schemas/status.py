"""Shapes of GET /projects/{id}/status (the readiness board)."""

from pydantic import BaseModel, Field

from app.core.validation import ValidationIssue


class StatusSection(BaseModel):
    id: str
    label: str
    configured: bool
    issue_count: int


class NextStep(BaseModel):
    id: str  # fix_issues | add_entity | consider_auth | generate
    title: str
    reason: str
    section: str  # a StatusSection id, or "generate"
    dismissed: bool = False  # true only on entries of `ProjectStatus.dismissed_steps`


class ProjectStatus(BaseModel):
    ready: bool
    issues: list[ValidationIssue]
    counts: dict[str, int]
    sections: list[StatusSection]
    next_step: NextStep
    # Dismissable steps the project has skipped (dismissed: true). They are never `next_step`
    # and never count as outstanding. Additive field; empty by default.
    dismissed_steps: list[NextStep] = []


class DismissBody(BaseModel):
    """Body of POST /projects/{id}/status/dismiss. `step` must be a dismissable step id
    (today: `consider_auth`); anything else is a 422."""

    step: str = Field(max_length=40)
