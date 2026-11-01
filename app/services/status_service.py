"""The readiness board: one validate call over the assembled spec, no generation, no writes."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.spec_models import Spec
from app.core.validation import ValidationIssue, validate
from app.schemas.status import NextStep, ProjectStatus, StatusSection
from app.services.spec_service import SpecService

SECTION_LABELS: tuple[tuple[str, str], ...] = (
    ("model", "Data model"),
    ("auth", "Sign-in"),
    ("authorization", "Roles and access"),
    ("payments", "Payments"),
    ("storage", "File storage"),
    ("observability", "Observability"),
    ("deployment", "Deployment"),
    ("documents", "Documents"),
    ("state_machines", "State machines"),
    ("settings", "Settings, sequences and lists"),
    ("history", "Change history"),
    ("hooks", "Custom hooks"),
    ("seed", "Seed data"),
)

# Top-level spec key of an issue path -> area. Anything not listed is the data model.
_PATH_AREA = {
    "auth": "auth",
    "payments": "payments",
    "storage": "storage",
    "authorization": "authorization",
    "observability": "observability",
    "deployment": "deployment",
    "documents": "documents",
    "state_machines": "state_machines",
    "settings": "settings",
    "sequences": "settings",
    "lists": "settings",
    "history": "history",
    "hooks": "hooks",
    "seed": "seed",
}


def issue_area(issue: ValidationIssue) -> str:
    """Same judgement as the dashboard's old `sectionForIssue`, extended to the behaviour areas."""
    if issue.code == "storage_required":
        return "storage"
    if issue.code.startswith("authz."):
        return "authorization"
    head = issue.path.split(".", 1)[0].split("[", 1)[0]
    if head == "auth" and issue.path.startswith(("auth.roles", "auth.permissions")):
        return "authorization"
    return _PATH_AREA.get(head, "model")


def _enabled(block: object | None) -> bool:
    return block is not None and bool(getattr(block, "enabled", True))


def build_status(spec: Spec, issues: list[ValidationIssue]) -> ProjectStatus:
    """Pure: turn a spec and its validation issues into the board.

    `ready` is true when the project has at least one entity and validation reports nothing.

    `next_step` priority (first match wins, deterministic):
      1. any validation issue: `fix_issues`, pointing at the area of the FIRST issue in
         validation order (validation walks the spec top-down, so this is stable);
      2. no entities: `add_entity` (section model);
      3. sign-in not enabled: `consider_auth` (section auth; optional, so it comes last);
      4. otherwise `generate`.
    """
    auth_on = _enabled(spec.auth)
    configured = {
        "model": bool(spec.entities),
        "auth": auth_on,
        "authorization": bool(
            (spec.auth is not None and spec.auth.roles)
            or (spec.authorization is not None and spec.authorization.policies)
        ),
        "payments": _enabled(spec.payments),
        "storage": _enabled(spec.storage),
        "observability": _enabled(spec.observability),
        "deployment": _enabled(spec.deployment),
        "documents": _enabled(spec.documents),
        "state_machines": bool(spec.state_machines),
        "settings": bool(spec.settings or spec.sequences or spec.lists),
        "history": bool(spec.history),
        "hooks": bool(spec.hooks),
        "seed": bool(spec.seed),
    }
    per_area: dict[str, int] = {}
    for issue in issues:
        area = issue_area(issue)
        per_area[area] = per_area.get(area, 0) + 1
    sections = [
        StatusSection(id=i, label=label, configured=configured[i], issue_count=per_area.get(i, 0))
        for i, label in SECTION_LABELS
    ]
    counts = {
        "entities": len(spec.entities),
        "relations": len(spec.relations),
        "state_machines": len(spec.state_machines),
        "settings": len(spec.settings),
        "sequences": len(spec.sequences),
        "lists": len(spec.lists),
        "history_configs": len(spec.history),
        "hooks": len(spec.hooks),
        "seed_profiles": len(spec.seed),
    }
    if issues:
        first = issues[0]
        n = len(issues)
        step = NextStep(
            id="fix_issues",
            title=f"Fix {n} {'problem' if n == 1 else 'problems'} before generating",
            reason=first.message,
            section=issue_area(first),
        )
    elif not spec.entities:
        step = NextStep(
            id="add_entity",
            title="Add your first entity",
            reason="A backend needs at least one thing to store, such as posts or customers.",
            section="model",
        )
    elif not auth_on:
        step = NextStep(
            id="consider_auth",
            title="Decide how people sign in",
            reason="Your API has no user accounts yet. Skip this if it does not need them.",
            section="auth",
        )
    else:
        step = NextStep(
            id="generate",
            title="Generate your backend",
            reason="The model is valid and nothing is left to fix.",
            section="generate",
        )
    return ProjectStatus(
        ready=bool(spec.entities) and not issues,
        issues=issues,
        counts=counts,
        sections=sections,
        next_step=step,
    )


class StatusService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, project_id: uuid.UUID) -> ProjectStatus:
        spec = await SpecService(self.session).assemble(project_id)  # 404 for an unknown project
        return build_status(spec, validate(spec))
