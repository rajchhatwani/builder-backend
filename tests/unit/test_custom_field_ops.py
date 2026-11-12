"""CP4F2-B: typed custom-field ops (plan / inverse / validation), the promote planner step and the
pure pre-flight cast check."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.core.custom_fields import check_promotable, preflight_cast
from app.core.spec_models import Spec, SpecCustomFieldDef
from app.core.validation import validate
from app.exceptions import AppError
from app.services.migration_planner import StepKind, plan_migration
from app.services.ops.canon import canonical_bytes
from app.services.ops.registry import REGISTRY, parse, plan

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "specs" / "custom_fields.json"


def spec() -> Spec:
    return Spec.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


def apply(before: Spec, op: str, payload: dict[str, Any]) -> Spec:
    return plan(before, op, payload).after


def defs(s: Spec, entity: str = "Contact") -> list[str]:
    e = next(x for x in s.entities if x.name == entity)
    return [d.name for d in (e.custom_fields.defs if e.custom_fields else [])]


def roundtrip(before: Spec, op: str, payload: dict[str, Any]) -> tuple[Spec, str]:
    p = plan(before, op, payload)
    back = REGISTRY[p.inverse_type].to_spec(p.after, parse(p.inverse_type, p.inverse_payload))
    assert canonical_bytes(back) == canonical_bytes(before)
    return p.after, p.inverse_type


def test_ops_are_registered() -> None:
    assert {"define_custom_field", "update_custom_field", "remove_custom_field", "promote_custom_field"} <= set(REGISTRY)


def test_define_has_typed_inverse_when_already_enabled() -> None:
    d = {"name": "region", "type": "string", "max_length": 10}
    after, inv = roundtrip(spec(), "define_custom_field", {"entity": "Contact", "def": d})
    assert defs(after)[-1] == "region" and inv == "remove_custom_field"
    assert validate(after) == []


def test_define_enables_custom_fields_and_falls_back_to_snapshot_inverse() -> None:
    d = {"name": "flag", "type": "bool"}
    after, inv = roundtrip(spec(), "define_custom_field", {"entity": "Note", "def": d})
    note = next(e for e in after.entities if e.name == "Note")
    assert note.custom_fields is not None and note.custom_fields.enabled
    assert inv == "replace_spec"  # removing the def does not undo enabling: only a snapshot is exact


def test_define_duplicate_unknown_entity_and_bad_payload() -> None:
    with pytest.raises(AppError) as e:
        apply(spec(), "define_custom_field", {"entity": "Contact", "def": {"name": "score", "type": "int"}})
    assert e.value.status_code == 409
    with pytest.raises(AppError) as e:
        apply(spec(), "define_custom_field", {"entity": "Nope", "def": {"name": "x", "type": "int"}})
    assert e.value.status_code == 404
    with pytest.raises(AppError) as e:
        parse("define_custom_field", {"entity": "Contact", "def": {"name": "x", "type": "int", "bogus": 1}})
    assert e.value.code == "invalid_op_payload"


@pytest.mark.parametrize(
    ("def_", "code"),
    [
        ({"name": "full_name", "type": "string"}, "custom_field_collision"),
        ({"name": "Bad-Name", "type": "int"}, "custom_field_bad_name"),
        ({"name": "x", "type": "decimal"}, "custom_field_bad_type"),
        ({"name": "x", "type": "int", "max_length": 4}, "custom_field_bad_option"),
    ],
)
def test_normal_spec_validation_catches_bad_defs(def_: dict[str, Any], code: str) -> None:
    after = apply(spec(), "define_custom_field", {"entity": "Contact", "def": def_})
    assert code in {i.code for i in validate(after)}


def test_update_and_remove_round_trip() -> None:
    after, inv = roundtrip(
        spec(), "update_custom_field", {"entity": "Contact", "name": "nickname", "changes": {"max_length": 80}}
    )
    assert "nickname" in defs(after) and inv == "update_custom_field"
    after, inv = roundtrip(spec(), "remove_custom_field", {"entity": "Contact", "name": "tier"})
    assert "tier" not in defs(after) and inv == "define_custom_field"
    with pytest.raises(AppError):
        parse("update_custom_field", {"entity": "Contact", "name": "score", "changes": {"bogus": 1}})
    with pytest.raises(AppError) as e:
        apply(spec(), "remove_custom_field", {"entity": "Contact", "name": "missing"})
    assert e.value.status_code == 404


def test_promote_is_snapshot_inverse_and_planner_sees_the_sql() -> None:
    before = spec()
    p = plan(before, "promote_custom_field", {"entity": "Contact", "name": "score"})
    contact = next(e for e in p.after.entities if e.name == "Contact")
    assert any(f.name == "score" and f.type == "integer" for f in contact.fields)
    assert "score" not in defs(p.after)
    assert p.inverse_type == "replace_spec"  # not re-creatable as a typed op; exact snapshot instead
    back = REGISTRY["replace_spec"].to_spec(p.after, parse(p.inverse_type, p.inverse_payload))
    assert canonical_bytes(back) == canonical_bytes(before)
    steps = plan_migration(before, p.after).steps
    promo = [s for s in steps if s.kind == StepKind.promote_custom_field]
    assert len(promo) == 1 and promo[0].sql_hint is not None
    assert 'UPDATE "contacts" SET "score" = (custom_fields->>\'score\')::integer' in promo[0].sql_hint
    with pytest.raises(AppError) as e:
        apply(before, "promote_custom_field", {"entity": "Contact", "name": "nope"})
    assert e.value.status_code == 404


# -- pre-flight --------------------------------------------------------------------------------


def d(type_: str, **kw: Any) -> SpecCustomFieldDef:
    return SpecCustomFieldDef(name="x", type=type_, **kw)


@pytest.mark.parametrize(
    ("definition", "samples", "codes"),
    [
        (d("int"), [1, "2", -5, None], []),
        (d("int"), [2**31, 1.5, "abc", True], ["custom_field_promote_int_out_of_range", "custom_field_promote_bad_value", "custom_field_promote_bad_value", "custom_field_promote_bad_value"]),
        (d("float"), [1, 2.5, "3.5", float("inf"), "x"], ["custom_field_promote_bad_value"] * 2),
        (d("bool"), [True, "false", 1, "maybe", {}], ["custom_field_promote_bad_value"] * 2),
        (d("date"), ["2024-02-29", "2024-13-01", 5], ["custom_field_promote_bad_date"] * 2),
        (d("datetime"), ["2024-02-29T10:00:00Z", "yesterday"], ["custom_field_promote_bad_datetime"]),
        (d("string", max_length=3), ["abc", "abcd", 12345], ["custom_field_promote_too_long"] * 2),
        (d("string"), ["x" * 255, "x" * 256], ["custom_field_promote_too_long"]),
        (d("string", enum_values=["a", "b"]), ["a", "c"], ["custom_field_promote_not_in_enum"]),
        (d("int", required=True), [1, None, 2, None], ["custom_field_promote_required_without_default"] * 2),
    ],
)
def test_preflight_cast_table(definition: SpecCustomFieldDef, samples: list[Any], codes: list[str]) -> None:
    got = preflight_cast(definition, samples)
    assert [p.code for p in got] == codes


def test_preflight_reports_the_sample_index_and_never_the_value() -> None:
    got = preflight_cast(d("int"), [1, "secret-value"])
    assert got[0].sample_index == 1 and "secret-value" not in got[0].message


def test_check_promotable_static_and_with_samples() -> None:
    s = spec()
    assert [p.code for p in check_promotable(s, "Contact", "nope")] == ["custom_field_promote_unavailable"]
    assert [p.code for p in check_promotable(s, "Nope", "score")] == ["custom_field_promote_unavailable"]
    plain = check_promotable(s, "Contact", "score")
    assert {p.code for p in plain} == {"custom_field_promote_type_change"} and all(p.severity == "warning" for p in plain)
    required = {p.code for p in check_promotable(s, "Contact", "tier")}
    assert "custom_field_promote_required_without_default" in required  # tier is required
    bad = check_promotable(s, "Contact", "tier", ["gold", "bronze", None])
    assert [p.code for p in bad if p.severity == "error"] == [
        "custom_field_promote_not_in_enum",
        "custom_field_promote_required_without_default",
    ]


def test_preflight_huge_numbers_do_not_raise() -> None:
    # SENTINEL M4: a >4300-digit integer string / a huge int float must be a problem, never a 500.
    assert [p.code for p in preflight_cast(d("int"), ["9" * 5000])] == ["custom_field_promote_int_out_of_range"]
    assert [p.code for p in preflight_cast(d("float"), [10**400])] == ["custom_field_promote_bad_value"]


def test_l7_rename_is_refused_with_a_stable_code() -> None:
    with pytest.raises(AppError) as e:
        apply(spec(), "update_custom_field", {"entity": "Contact", "name": "nickname", "changes": {"name": "alias"}})
    assert e.value.code == "custom_field_rename_unsupported" and e.value.status_code == 409
    # a no-op "rename" to the same name and other changes stay allowed
    after = apply(spec(), "update_custom_field", {"entity": "Contact", "name": "nickname", "changes": {"name": "nickname", "max_length": 9}})
    assert "nickname" in defs(after)


def test_l7_define_that_enables_restores_the_exact_spec_on_undo() -> None:
    before = spec()
    p = plan(before, "define_custom_field", {"entity": "Note", "def": {"name": "flag", "type": "bool"}})
    back = REGISTRY[p.inverse_type].to_spec(p.after, parse(p.inverse_type, p.inverse_payload))
    assert canonical_bytes(back) == canonical_bytes(before)
    note = next(e for e in back.entities if e.name == "Note")
    assert note.custom_fields is None or not note.custom_fields.enabled
