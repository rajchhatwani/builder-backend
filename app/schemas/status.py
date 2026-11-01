"""Shapes of GET /projects/{id}/status (the readiness board)."""

from pydantic import BaseModel

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


class ProjectStatus(BaseModel):
    ready: bool
    issues: list[ValidationIssue]
    counts: dict[str, int]
    sections: list[StatusSection]
    next_step: NextStep
