"""Pure logic of dismissable next steps and per-section versions."""

import pytest

from app.core.spec_models import Spec, SpecEntity, SpecProject
from app.exceptions import AppError
from app.models.behavior_config import ProjectBehavior
from app.services.behavior_service import DISMISSED_KEY, _dismissed, apply_section, section_version
from app.services.status_service import DISMISSABLE_STEPS, build_status, check_dismissable


def spec_with_entity() -> Spec:
    return Spec(
        project=SpecProject(name="P", slug="p"),
        entities=[SpecEntity(name="Item", table_name="items", plural_path="items", fields=[])],
    )


def test_consider_auth_is_skipped_when_dismissed() -> None:
    plain = build_status(spec_with_entity(), [])
    assert plain.next_step.id == "consider_auth" and plain.dismissed_steps == []
    skipped = build_status(spec_with_entity(), [], frozenset({"consider_auth"}))
    assert skipped.next_step.id == "generate"
    assert [(s.id, s.dismissed) for s in skipped.dismissed_steps] == [("consider_auth", True)]


def test_only_declared_steps_are_dismissable() -> None:
    assert DISMISSABLE_STEPS == ("consider_auth",)
    assert check_dismissable("consider_auth") == "consider_auth"
    for bad in ("generate", "fix_issues", "add_entity", "", "x"):
        with pytest.raises(AppError) as err:
            check_dismissable(bad)
        assert err.value.status_code == 422


def test_apply_section_bumps_only_its_own_version() -> None:
    row = ProjectBehavior(project_id=None, version=1, sections={})  # type: ignore[arg-type]
    apply_section(row, "settings", [])
    apply_section(row, "settings", [])
    apply_section(row, "hooks", [])
    assert section_version(row, "settings") == 2 and section_version(row, "hooks") == 1
    assert section_version(row, "seed") == 0 and section_version(None, "seed") == 0


def test_legacy_rows_and_bad_dismissed_values_are_safe() -> None:
    legacy = ProjectBehavior(project_id=None, version=7, sections={"settings": []})  # type: ignore[arg-type]
    assert section_version(legacy, "settings") == 0
    junk = ProjectBehavior(project_id=None, version=1, sections={DISMISSED_KEY: "oops"})  # type: ignore[arg-type]
    assert _dismissed(junk) == [] and _dismissed(None) == []
