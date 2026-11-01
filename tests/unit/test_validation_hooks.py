"""Hook validation: every way the `hooks` section can be wrong is reported with a path and a code."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.core.generator import InvalidSpecError, generate
from app.core.spec_models import Spec
from app.core.validation import validate
from app.core.validation_hooks import CEILINGS, default_policy, parse_point

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def spec_with(change: Any = None) -> Spec:
    data: dict[str, Any] = copy.deepcopy(
        json.loads((FIXTURES / "hooks_invoice.json").read_text(encoding="utf-8"))
    )
    if change is not None:
        change(data)
    return Spec.model_validate(data)


def codes(spec: Spec) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in validate(spec)}


def one_hook(**changes: Any) -> Any:
    """A change function that updates the first hook (the match_invoice guard)."""

    def apply(d: dict[str, Any]) -> None:
        d["hooks"][0].update(changes)

    return apply


def test_the_example_is_valid_and_generates() -> None:
    assert validate(spec_with()) == []
    assert "app/custom/hooks/match_invoice.py" in generate(spec_with())


def test_no_hooks_section_generates_none_of_the_hook_files() -> None:
    def clear(d: dict[str, Any]) -> None:
        d["hooks"] = []

    files = generate(spec_with(clear))
    assert not [p for p in files if "hooks_gen" in p or "platform_sdk" in p or "custom/hooks" in p]
    assert "platform/hooks.json" not in files and "app/platform_gate.py" not in files


def test_an_invalid_spec_does_not_generate() -> None:
    with pytest.raises(InvalidSpecError):
        generate(spec_with(one_hook(point="Ghost.after_save")))


@pytest.mark.parametrize("name", ["Match", "1abc", "has-dash", "x" * 41, "", "class", "print", "list"])
def test_bad_hook_names(name: str) -> None:
    assert ("hooks[0].name", "invalid_value") in codes(spec_with(one_hook(name=name)))


def test_names_are_unique() -> None:
    def twice(d: dict[str, Any]) -> None:
        second = copy.deepcopy(d["hooks"][1])
        second["name"] = "match_invoice"
        d["hooks"][1] = second

    assert ("hooks[1].name", "duplicate_name") in codes(spec_with(twice))


@pytest.mark.parametrize(
    "point",
    [
        "Invoice",
        "Invoice.before_delete",
        "Invoice.transition_guard",
        "Invoice.transition_guard()",
        "Invoice.transition_guard(Submit)",
        "invoice.after_save",
        "Invoice.after_save.extra",
        "Invoice.transition_guard(submit) ",
        " Invoice.after_save",
    ],
)
def test_malformed_points(point: str) -> None:
    assert ("hooks[0].point", "invalid_value") in codes(spec_with(one_hook(point=point)))


def test_parse_point_accepts_exactly_the_catalogue() -> None:
    assert parse_point("Invoice.before_save") == ("Invoice", "before_save", None)
    assert parse_point("Invoice.validate") == ("Invoice", "validate", None)
    assert parse_point("Invoice.transition_guard(submit)") == ("Invoice", "transition_guard", "submit")
    assert parse_point("Invoice.save") is None


def test_the_entity_and_the_transition_must_exist() -> None:
    assert ("hooks[0].point", "unknown_entity") in codes(spec_with(one_hook(point="Ghost.after_save")))
    found = codes(spec_with(one_hook(point="Invoice.transition_guard(nope)")))
    assert ("hooks[0].point", "unknown_transition") in found


def test_a_guard_needs_a_manual_transition_of_a_state_machine() -> None:
    found = codes(spec_with(one_hook(point="Invoice.transition_guard(auto_approve)")))
    assert ("hooks[0].point", "invalid_value") in found

    def no_machine(d: dict[str, Any]) -> None:
        d["state_machines"] = []

    assert ("hooks[0].point", "unknown_transition") in codes(spec_with(no_machine))


def test_kind_is_closed_and_effects_run_only_after_commit() -> None:
    assert ("hooks[0].kind", "invalid_value") in codes(spec_with(one_hook(kind="magic")))
    found = codes(spec_with(one_hook(kind="effect")))
    assert ("hooks[0].kind", "invalid_value") in found

    def effect_before(d: dict[str, Any]) -> None:
        d["hooks"][1]["point"] = "Invoice.after_save"

    assert ("hooks[1].kind", "invalid_value") in codes(spec_with(effect_before))


@pytest.mark.parametrize("name", ["match", "Match Input", "None", "Exception", "BaseModel", "Field"])
def test_model_names_are_camel_case_and_not_python_names(name: str) -> None:
    def rename(d: dict[str, Any]) -> None:
        d["hooks"][0]["input"]["name"] = name

    assert ("hooks[0].input.name", "invalid_value") in codes(spec_with(rename))


def test_model_names_are_unique_across_hooks_and_within_a_hook() -> None:
    def clash(d: dict[str, Any]) -> None:
        d["hooks"][1]["input"]["name"] = "MatchInput"
        d["hooks"][0]["output"]["name"] = "MatchInput"

    found = codes(spec_with(clash))
    assert ("hooks[1].input.name", "duplicate_name") in found
    assert ("hooks[0].output.name", "duplicate_name") in found


@pytest.mark.parametrize("name", ["Amount", "1x", "class", "model_x", "json", "copy", "a-b", "x" * 41, "_hidden"])
def test_bad_field_names(name: str) -> None:
    def rename(d: dict[str, Any]) -> None:
        d["hooks"][0]["input"]["fields"][0]["name"] = name

    assert ("hooks[0].input.fields[0].name", "invalid_value") in codes(spec_with(rename))


def test_field_names_are_unique_and_types_closed() -> None:
    def bad(d: dict[str, Any]) -> None:
        fields = d["hooks"][0]["input"]["fields"]
        fields[1]["name"] = "invoice_no"
        fields[2]["type"] = "list"

    found = codes(spec_with(bad))
    assert ("hooks[0].input.fields[1].name", "duplicate_name") in found
    assert ("hooks[0].input.fields[2].type", "invalid_value") in found


def test_field_counts_are_limited_and_input_cannot_be_empty() -> None:
    def many(d: dict[str, Any]) -> None:
        d["hooks"][1]["output"]["fields"] = [
            {"name": f"f{i}", "type": "int", "required": False} for i in range(31)
        ]

    assert ("hooks[1].output.fields", "too_many") in codes(spec_with(many))

    def empty(d: dict[str, Any]) -> None:
        d["hooks"][0]["input"]["fields"] = []

    assert ("hooks[0].input.fields", "required") in codes(spec_with(empty))


def test_input_fields_must_be_fields_of_the_entity_with_the_same_type() -> None:
    def bad(d: dict[str, Any]) -> None:
        fields = d["hooks"][0]["input"]["fields"]
        fields[0]["name"] = "ghost"
        fields[1]["type"] = "int"
        d["hooks"][1]["input"]["fields"][0]["type"] = "string"  # id is a uuid

    found = codes(spec_with(bad))
    assert ("hooks[0].input.fields[0].name", "unknown_field") in found
    assert ("hooks[0].input.fields[1].type", "type_mismatch") in found
    assert ("hooks[1].input.fields[0].type", "type_mismatch") in found


def test_a_guard_returns_allowed_and_an_optional_reason_only() -> None:
    def bad(d: dict[str, Any]) -> None:
        d["hooks"][0]["output"]["fields"] = [
            {"name": "allowed", "type": "string", "required": True},
            {"name": "extra", "type": "int", "required": False},
        ]

    found = codes(spec_with(bad))
    assert ("hooks[0].output.fields", "invalid_value") in found
    assert ("hooks[0].output.fields[1].name", "invalid_value") in found

    def missing(d: dict[str, Any]) -> None:
        d["hooks"][0]["output"]["fields"] = [{"name": "reason", "type": "string", "required": False}]

    assert ("hooks[0].output.fields", "required") in codes(spec_with(missing))


def validate_hook(**changes: Any) -> Any:
    def apply(d: dict[str, Any]) -> None:
        hook = copy.deepcopy(d["hooks"][0])
        hook["name"] = "check_invoice"
        hook["point"] = "Invoice.validate"
        hook["input"]["name"] = "CheckInput"
        hook["output"] = {
            "name": "CheckResult",
            "fields": [
                {"name": "valid", "type": "bool", "required": True},
                {"name": "message", "type": "string", "required": False},
            ],
        }
        hook.update(changes)
        d["hooks"].append(hook)

    return apply


def test_a_validate_hook_returns_valid_and_a_message() -> None:
    assert validate(spec_with(validate_hook())) == []
    found = codes(spec_with(validate_hook(failure_policy="fail_open")))
    assert ("hooks[2].failure_policy", "invalid_value") in found


def test_before_save_output_names_settable_entity_fields() -> None:
    def hook(fields: list[dict[str, Any]]) -> Any:
        def apply(d: dict[str, Any]) -> None:
            h = copy.deepcopy(d["hooks"][0])
            h.update(
                name="tidy", point="Invoice.before_save", failure_policy=None,
                input={"name": "TidyInput", "fields": [{"name": "invoice_no", "type": "string", "required": True}]},
                output={"name": "TidyResult", "fields": fields},
            )
            d["hooks"].append(h)

        return apply

    good = [{"name": "invoice_no", "type": "string", "required": False}]
    assert validate(spec_with(hook(good))) == []
    for field, code in (
        ({"name": "ghost", "type": "string", "required": False}, "unknown_field"),
        ({"name": "status", "type": "string", "required": False}, "invalid_value"),  # the state field
        ({"name": "id", "type": "uuid", "required": False}, "invalid_value"),
        ({"name": "amount", "type": "string", "required": False}, "type_mismatch"),
    ):
        assert ("hooks[2].output.fields[0].name", code) in codes(spec_with(hook([field]))) or (
            "hooks[2].output.fields[0].type", code
        ) in codes(spec_with(hook([field])))
    assert ("hooks[2].output.fields", "required") in codes(spec_with(hook([])))


def test_failure_policy_rules() -> None:
    assert ("hooks[0].failure_policy", "invalid_value") in codes(spec_with(one_hook(failure_policy="maybe")))
    assert ("hooks[0].failure_policy", "invalid_value") in codes(spec_with(one_hook(failure_policy="fail_open")))
    assert ("hooks[0].failure_policy", "invalid_value") in codes(
        spec_with(one_hook(failure_policy="fallback", fallback={"allowed": True}))
    )

    def commit_closed(d: dict[str, Any]) -> None:
        d["hooks"][1]["failure_policy"] = "fail_closed"

    assert ("hooks[1].failure_policy", "invalid_value") in codes(spec_with(commit_closed))


def test_defaults_follow_the_point() -> None:
    spec = spec_with()
    assert default_policy(spec.hooks[0]) == "fail_closed"
    assert default_policy(spec.hooks[1]) == "fail_open"


def test_fallback_values_must_match_the_output_model() -> None:
    def effect(**changes: Any) -> Any:
        def apply(d: dict[str, Any]) -> None:
            d["hooks"][1].update(failure_policy="fallback", **changes)

        return apply

    assert validate(spec_with(effect(fallback={"sent": False}))) == []
    assert ("hooks[1].fallback", "required") in codes(spec_with(effect()))
    assert ("hooks[1].fallback", "required") in codes(spec_with(effect(fallback={})))
    assert ("hooks[1].fallback.sent", "invalid_value") in codes(spec_with(effect(fallback={"sent": "yes"})))
    assert ("hooks[1].fallback.nope", "unknown_field") in codes(spec_with(effect(fallback={"sent": True, "nope": 1})))

    def stray(d: dict[str, Any]) -> None:
        d["hooks"][1]["fallback"] = {"sent": True}

    assert ("hooks[1].fallback", "invalid_value") in codes(spec_with(stray))


def test_budgets_stay_under_their_ceilings() -> None:
    pure, effect = CEILINGS["pure"], CEILINGS["effect"]
    assert pure["rows"] == 0 and effect["outbound_calls"] == 0

    def budget(i: int, **values: int) -> Any:
        def apply(d: dict[str, Any]) -> None:
            d["hooks"][i]["budget"].update(values)

        return apply

    assert ("hooks[0].budget.cpu_ms", "over_ceiling") in codes(spec_with(budget(0, cpu_ms=pure["cpu_ms"] + 1)))
    assert ("hooks[0].budget.cpu_ms", "over_ceiling") in codes(spec_with(budget(0, cpu_ms=0)))
    assert ("hooks[0].budget.rows", "over_ceiling") in codes(spec_with(budget(0, rows=1)))
    assert ("hooks[0].budget.outbound_calls", "over_ceiling") in codes(spec_with(budget(0, outbound_calls=1)))
    assert ("hooks[1].budget.cpu_ms", "over_ceiling") in codes(spec_with(budget(1, cpu_ms=effect["cpu_ms"] + 1)))
    assert ("hooks[1].budget.rows", "over_ceiling") in codes(spec_with(budget(1, rows=effect["rows"] + 1)))
    assert ("hooks[1].budget.rows", "over_ceiling") in codes(spec_with(budget(1, rows=-1)))
    assert validate(spec_with(budget(1, cpu_ms=effect["cpu_ms"]))) == []


def test_reads_and_rows_go_together_and_only_for_effects() -> None:
    def reads(i: int, **changes: Any) -> Any:
        def apply(d: dict[str, Any]) -> None:
            d["hooks"][i].update(changes)

        return apply

    assert ("hooks[1].reads[0]", "unknown_entity") in codes(spec_with(reads(1, reads=["Ghost"])))
    assert ("hooks[1].reads[1]", "duplicate_name") in codes(spec_with(reads(1, reads=["Invoice", "Invoice"])))
    assert ("hooks[1].reads", "required") in codes(spec_with(reads(1, reads=[])))
    assert ("hooks[0].reads", "invalid_value") in codes(spec_with(reads(0, reads=["Invoice"])))

    def rows_zero(d: dict[str, Any]) -> None:
        d["hooks"][1]["budget"]["rows"] = 0

    assert ("hooks[1].budget.rows", "required") in codes(spec_with(rows_zero))


def test_there_is_a_limit_on_the_number_of_hooks() -> None:
    def many(d: dict[str, Any]) -> None:
        d["hooks"] = [d["hooks"][0]] * 51

    assert ("hooks", "too_many") in codes(spec_with(many))


def test_the_spec_round_trips_through_json() -> None:
    spec = spec_with()
    again = Spec.model_validate_json(spec.model_dump_json())
    assert again == spec
