"""B2-11: apply_section stores a single-object block (and null) and bumps only its own version."""

import json
from pathlib import Path

from app.core.spec_models import Spec
from app.models.behavior_config import ProjectBehavior
from app.services.behavior_service import BLOCKS, SECTIONS, apply_section, section_version

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "specs" / "combined_async.json"


def test_block_stored_versioned_and_removed() -> None:
    spec = Spec.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    row = ProjectBehavior(sections={}, version=1)
    assert spec.jobs is not None
    apply_section(row, "jobs", spec.jobs)
    assert row.sections["jobs"] == spec.jobs.model_dump(mode="json")
    assert section_version(row, "jobs") == 1 and section_version(row, "events") == 0
    apply_section(row, "jobs", None)
    assert row.sections["jobs"] is None and section_version(row, "jobs") == 2


def test_every_block_is_a_section_and_a_spec_field() -> None:
    assert set(BLOCKS) <= set(SECTIONS) and set(BLOCKS) <= set(Spec.model_fields)


# -- A-009: every block, not just jobs --------------------------------------------------------

import pytest  # noqa: E402

from app.exceptions import AppError  # noqa: E402
from app.services import behavior_service as bsvc  # noqa: E402

SPECS = FIXTURE.parent


def _sample(block: str) -> object:
    """The first fixture spec that declares `block` (a real, validated model, not a stub)."""
    for path in sorted(SPECS.glob("*.json")):
        spec = Spec.model_validate(json.loads(path.read_text(encoding="utf-8")))
        value = getattr(spec, block)
        if value is not None:
            return value
    raise AssertionError(f"no fixture spec declares the {block} block; add one")


@pytest.mark.parametrize("block", BLOCKS)
def test_each_block_round_trips_through_its_own_model(block: str) -> None:
    model = _sample(block)
    row = ProjectBehavior(sections={}, version=1)
    with bsvc.system_actor():
        apply_section(row, block, model)  # type: ignore[arg-type]
    stored = row.sections[block]
    assert stored == model.model_dump(mode="json")  # type: ignore[attr-defined]
    assert type(model).model_validate(stored) == model  # what was stored loads back identically
    assert section_version(row, block) == 1
    assert all(section_version(row, other) == 0 for other in BLOCKS if other != block)


def test_block_models_cover_exactly_the_blocks() -> None:
    assert set(bsvc._BLOCK_MODELS) == set(BLOCKS)
    for key, model in bsvc._BLOCK_MODELS.items():
        assert Spec.model_fields[key].annotation is not None
        assert model.__name__.startswith("Spec")


def test_saving_one_block_keeps_the_others_and_their_versions() -> None:
    row = ProjectBehavior(sections={}, version=1)
    with bsvc.system_actor():
        for block in BLOCKS:
            apply_section(row, block, _sample(block))  # type: ignore[arg-type]
        apply_section(row, "jobs", None)
        apply_section(row, "events", _sample("events"))  # type: ignore[arg-type]
    assert row.sections["jobs"] is None
    assert section_version(row, "jobs") == 2 and section_version(row, "events") == 2
    for other in BLOCKS:
        if other not in ("jobs", "events"):
            assert section_version(row, other) == 1
            assert row.sections[other] is not None


def test_apply_section_assigns_a_new_dict_so_jsonb_sees_the_change() -> None:
    row = ProjectBehavior(sections={}, version=1)
    before = row.sections
    with bsvc.system_actor():
        apply_section(row, "events", _sample("events"))  # type: ignore[arg-type]
    assert row.sections is not before and before == {}


def test_effectful_hook_opt_in_is_owner_or_system_only() -> None:
    effects = _sample("hook_effects")
    for role in (None, "editor", "viewer"):
        token = bsvc.ACTOR_ROLE.set(role)
        try:
            row = ProjectBehavior(sections={}, version=1)
            with pytest.raises(AppError) as err:
                apply_section(row, "hook_effects", effects)  # type: ignore[arg-type]
            assert err.value.status_code == 403
            assert "hook_effects" not in row.sections  # nothing was written
        finally:
            bsvc.ACTOR_ROLE.reset(token)
    for role in ("owner", bsvc.SYSTEM_ACTOR):
        token = bsvc.ACTOR_ROLE.set(role)
        try:
            row = ProjectBehavior(sections={}, version=1)
            apply_section(row, "hook_effects", effects)  # type: ignore[arg-type]
            assert row.sections["hook_effects"] is not None
        finally:
            bsvc.ACTOR_ROLE.reset(token)


def test_an_editor_may_resave_an_unchanged_effects_block() -> None:
    effects = _sample("hook_effects")
    row = ProjectBehavior(sections={}, version=1)
    with bsvc.system_actor():
        apply_section(row, "hook_effects", effects)  # type: ignore[arg-type]
    token = bsvc.ACTOR_ROLE.set("editor")
    try:
        apply_section(row, "hook_effects", effects)  # type: ignore[arg-type]  # unchanged: allowed
    finally:
        bsvc.ACTOR_ROLE.reset(token)
    assert section_version(row, "hook_effects") == 2
