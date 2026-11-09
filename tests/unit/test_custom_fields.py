"""C2 custom fields: definition validation, promotion to a column (spec transform + Alembic text),
the planner wiring and the generated runtime validator."""

import ast
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from app.core.custom_fields import CustomFieldError, promote
from app.core.spec_models import Spec
from app.core.validation import validate
from app.services.migration_planner import StepKind, plan_migration

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures" / "specs" / "custom_fields.json"
RUNTIME = (
    ROOT.parent / "app/core/generator/features/crud/templates/app/core/custom_fields.py.tpl"
)


def spec(**cf: Any) -> Spec:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["entities"][0]["custom_fields"].update(cf)
    return Spec.model_validate(raw)


def codes(s: Spec) -> set[str]:
    return {i.code for i in validate(s)}


def test_fixture_is_valid() -> None:
    assert validate(spec()) == []


@pytest.mark.parametrize(
    ("defs", "code"),
    [
        ([{"name": "Bad-Name", "type": "int"}], "custom_field_bad_name"),
        ([{"name": "full_name", "type": "string"}], "custom_field_collision"),
        ([{"name": "custom_fields", "type": "string"}], "custom_field_collision"),
        ([{"name": "created_at", "type": "date"}], "custom_field_collision"),
        ([{"name": "a", "type": "int"}, {"name": "a", "type": "int"}], "custom_field_collision"),
        ([{"name": "a", "type": "decimal"}], "custom_field_bad_type"),
        ([{"name": "a", "type": "int", "max_length": 5}], "custom_field_bad_option"),
        ([{"name": "a", "type": "string", "enum_values": []}], "custom_field_bad_option"),
        ([{"name": "select", "type": "int"}], "custom_field_bad_name"),
    ],
)
def test_definition_errors_have_stable_codes(defs: list[dict[str, Any]], code: str) -> None:
    assert code in codes(spec(defs=defs))


def test_too_many_defs_and_bad_limits() -> None:
    many = [{"name": f"k{i}", "type": "int"} for i in range(30)]
    assert "custom_field_too_many" in codes(spec(defs=many, max_keys=20))
    assert "custom_field_bad_limit" in codes(spec(max_bytes=0))



def test_a_real_field_named_custom_fields_is_refused_when_enabled() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["entities"][0]["fields"].append({"name": "custom_fields", "type": "json"})
    assert "custom_field_collision" in codes(Spec.model_validate(raw))


@pytest.mark.parametrize(
    ("name", "column_type", "cast"),
    [
        ("score", "integer", "::integer"),
        ("rating", "float", "::double precision"),
        ("vip", "boolean", "::boolean"),
        ("birthday", "date", "::date"),
        ("last_seen", "datetime", "::timestamptz"),
        ("nickname", "string", "->>'nickname'"),
        ("tier", "enum", "->>'tier'"),
    ],
)
def test_promote_each_type(name: str, column_type: str, cast: str) -> None:
    before = spec()
    after, plan = promote(before, "Contact", name)
    entity = after.entities[0]
    field = next(f for f in entity.fields if f.name == name)
    assert field.type == column_type
    assert name not in {d.name for d in entity.custom_fields.defs}  # type: ignore[union-attr]
    assert validate(after) == []
    assert name in {d.name for d in before.entities[0].custom_fields.defs}  # type: ignore[union-attr]
    text = plan.render_migration("c2000001", "0001")
    ast.parse(text)
    assert f"{cast}" in text
    assert "UPDATE contacts SET " + name in text
    assert f"custom_fields - '{name}'" in text
    assert "jsonb_build_object" in text and "drop_column" in text and "IS NOT NULL" in text
    assert "down_revision: str | None = '0001'" in text


def test_required_promotion_guards_and_sets_not_null() -> None:
    _, plan = promote(spec(), "Contact", "tier")
    text = plan.render_migration("c2000001", "0001")
    assert "raise RuntimeError" in text and "nullable=False" in text
    assert text.index("raise RuntimeError") < text.index("nullable=False")
    _, optional = promote(spec(), "Contact", "score")
    assert "raise RuntimeError" not in optional.render_migration("c2000001", "0001")
    assert "nullable=False" not in optional.render_migration("c2000001", "0001")


def test_plan_is_deterministic_and_promotion_is_not_repeatable() -> None:
    s = spec()
    a_spec, a = promote(s, "Contact", "score")
    b_spec, b = promote(s, "Contact", "score")
    assert a == b and a.render_migration("x1", "0001") == b.render_migration("x1", "0001")
    assert a_spec.model_dump() == b_spec.model_dump()
    with pytest.raises(CustomFieldError):
        promote(a_spec, "Contact", "score")


def test_promote_refuses_unknown_entity_def_and_disabled() -> None:
    s = spec()
    with pytest.raises(CustomFieldError):
        promote(s, "Nope", "score")
    with pytest.raises(CustomFieldError):
        promote(s, "Contact", "missing")
    with pytest.raises(CustomFieldError):
        promote(s, "Note", "score")


def test_planner_renders_a_def_to_field_move_as_a_data_moving_step() -> None:
    old = spec()
    new, _ = promote(old, "Contact", "score")
    plan = plan_migration(old, new)
    kinds = [s.kind for s in plan.steps]
    assert kinds == [StepKind.promote_custom_field]
    step = plan.steps[0]
    assert step.sql_hint is not None and "custom_fields ->>" not in step.sql_hint
    assert "UPDATE" in step.sql_hint and "custom_fields - 'score'" in step.sql_hint
    assert not plan.requires_confirmation
    required = plan_migration(old, promote(old, "Contact", "tier")[0])
    assert required.requires_backfill


def test_planner_plain_add_column_when_there_was_no_def() -> None:
    old = spec()
    new = old.model_copy(deep=True)
    from app.core.spec_models import SpecField

    new.entities[0].fields.append(SpecField(name="other", type="integer"))
    plan = plan_migration(old, new)
    assert [s.kind for s in plan.steps] == [StepKind.add_column]
    assert plan_migration(old, old).is_empty


def test_planner_adds_the_custom_fields_column_when_enabled_later() -> None:
    old = spec(enabled=False)
    plan = plan_migration(old, spec())
    assert [(s.kind, s.field) for s in plan.steps] == [(StepKind.add_column, "custom_fields")]
    assert not plan.requires_confirmation


# --- the generated runtime validator -----------------------------------------------------


@pytest.fixture(scope="module")
def runtime() -> Any:
    loader = importlib.util.spec_from_loader("gen_custom_fields", loader=None)
    assert loader is not None
    module = importlib.util.module_from_spec(loader)
    exec(compile(RUNTIME.read_text(encoding="utf-8"), str(RUNTIME), "exec"), module.__dict__)
    return module


DEFS = (
    ("n", "int", False, None, None),
    ("f", "float", False, None, None),
    ("b", "bool", False, None, None),
    ("s", "string", True, 5, None),
    ("d", "date", False, None, None),
    ("t", "datetime", False, None, None),
    ("e", "string", False, None, ("x", "y")),
)


def check(runtime: Any, value: dict[str, Any], **kw: int) -> dict[str, Any]:
    return runtime.validate(value, DEFS, max_keys=kw.get("max_keys", 10), max_bytes=kw.get("max_bytes", 500))


def test_runtime_accepts_and_normalises(runtime: Any) -> None:
    out = check(runtime, {"s": "ok", "n": 3, "f": 2, "b": False, "d": "2026-01-02", "t": "2026-01-02T03:04:05", "e": "x"})
    assert out["f"] == 2.0 and out["t"].endswith("+00:00") and out["n"] == 3
    assert check(runtime, {"s": "ok", "n": None}) == {"s": "ok"}


@pytest.mark.parametrize(
    "value",
    [
        {},  # required missing
        {"s": "ok", "zzz": 1},  # unknown key
        {"s": "toolong"},
        {"s": "ok", "n": "5"},
        {"s": "ok", "n": True},
        {"s": "ok", "n": 2**31},
        {"s": "ok", "b": 1},
        {"s": "ok", "f": float("nan")},
        {"s": "ok", "d": "2026-13-40"},
        {"s": "ok", "t": "nope"},
        {"s": "ok", "e": "z"},
        {"s": 5},
    ],
)
def test_runtime_rejects(runtime: Any, value: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        check(runtime, value)


def test_runtime_caps_keys_and_bytes(runtime: Any) -> None:
    with pytest.raises(ValueError):
        check(runtime, {"s": "ok", "n": 1}, max_keys=1)
    with pytest.raises(ValueError):
        check(runtime, {"s": "ok", "n": 1}, max_bytes=5)
