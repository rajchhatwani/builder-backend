"""S2-016: with no actor role, effectful-hook changes are denied; only owner or the explicit
system marker may make them."""

import pytest

from app.core.spec_models import SpecHook, SpecHookModel
from app.exceptions import AppError
from app.models.behavior_config import ProjectBehavior
from app.services.behavior_service import ACTOR_ROLE, apply_section, system_actor


def _effect_hook() -> SpecHook:
    return SpecHook(
        name="notify",
        point="Order.after_commit",
        kind="effect",
        input=SpecHookModel(name="In"),
        output=SpecHookModel(name="Out"),
        effects=["email"],
    )


def _row() -> ProjectBehavior:
    return ProjectBehavior(sections={}, version=1)


def _apply(row: ProjectBehavior) -> None:
    apply_section(row, "hooks", [_effect_hook()])


def test_no_actor_role_is_denied() -> None:
    assert ACTOR_ROLE.get() is None
    row = _row()
    with pytest.raises(AppError) as exc:
        _apply(row)
    assert exc.value.status_code == 403
    assert "hooks" not in row.sections


def test_system_marker_is_allowed_and_resets() -> None:
    row = _row()
    with system_actor():
        _apply(row)
    assert row.sections["hooks"][0]["effects"] == ["email"]
    assert ACTOR_ROLE.get() is None
    with pytest.raises(AppError):
        _apply(_row())


def test_owner_allowed_editor_denied() -> None:
    token = ACTOR_ROLE.set("owner")
    try:
        row = _row()
        _apply(row)
        assert row.sections["hooks"][0]["effects"] == ["email"]
    finally:
        ACTOR_ROLE.reset(token)
    token = ACTOR_ROLE.set("editor")
    try:
        with pytest.raises(AppError):
            _apply(_row())
    finally:
        ACTOR_ROLE.reset(token)


def test_no_role_still_allows_effect_free_changes() -> None:
    row = _row()
    apply_section(row, "hooks", [])
    assert row.sections["hooks"] == []
