"""The readiness board: one validate call over the assembled spec, no generation, no writes."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.spec_models import Spec
from app.core.validation import ValidationIssue, validate
from app.exceptions import AppError
from app.schemas.status import NextStep, ProjectStatus, StatusSection
from app.services.behavior_service import BehaviorService
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


# Next steps a user may skip. Only optional suggestions belong here; `fix_issues`, `add_entity`
# and `generate` can never be dismissed.
DISMISSABLE_STEPS: tuple[str, ...] = ("consider_auth",)


def check_dismissable(step: str) -> str:
    if step not in DISMISSABLE_STEPS:
        raise AppError(
            code="step_not_dismissable",
            message=f"'{step}' cannot be dismissed; dismissable steps: {', '.join(DISMISSABLE_STEPS)}",
            status_code=422,
        )
    return step


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


_CONSIDER_AUTH = NextStep(
    id="consider_auth",
    title="Decide how people sign in",
    reason="Your API has no user accounts yet. Skip this if it does not need them.",
    section="auth",
)
_DISMISSABLE_CATALOG: tuple[NextStep, ...] = (_CONSIDER_AUTH,)


def build_status(
    spec: Spec, issues: list[ValidationIssue], dismissed: frozenset[str] = frozenset()
) -> ProjectStatus:
    """Pure: turn a spec and its validation issues into the board.

    `ready` is true when the project has at least one entity and validation reports nothing.

    `next_step` priority (first match wins, deterministic):
      1. any validation issue: `fix_issues`, pointing at the area of the FIRST issue in
         validation order (validation walks the spec top-down, so this is stable);
      2. no entities: `add_entity` (section model);
      3. sign-in not enabled and `consider_auth` not dismissed: `consider_auth` (section auth;
         optional, so it comes last);
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
    elif not auth_on and "consider_auth" not in dismissed:
        step = _CONSIDER_AUTH
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
        dismissed_steps=[
            s.model_copy(update={"dismissed": True})
            for s in _DISMISSABLE_CATALOG
            if s.id in dismissed
        ],
    )


class StatusService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, project_id: uuid.UUID) -> ProjectStatus:
        spec = await SpecService(self.session).assemble(project_id)  # 404 for an unknown project
        dismissed = await BehaviorService(self.session).dismissed_steps(project_id)
        return build_status(spec, validate(spec), frozenset(dismissed))

    async def dismiss(self, project_id: uuid.UUID, step: str) -> ProjectStatus:
        await BehaviorService(self.session).set_dismissed(project_id, check_dismissable(step), True)
        return await self.get(project_id)

    async def undo_dismiss(self, project_id: uuid.UUID, step: str) -> ProjectStatus:
        await BehaviorService(self.session).set_dismissed(
            project_id, check_dismissable(step), False
        )
        return await self.get(project_id)
