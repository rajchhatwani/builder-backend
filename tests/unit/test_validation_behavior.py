"""State machine validation: every way a machine can be wrong is reported with a path and a code."""

import copy
import json
from pathlib import Path
from typing import Any

from app.core.spec_models import Spec
from app.core.validation import validate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def spec_with(change: Any = None) -> Spec:
    data: dict[str, Any] = json.loads((FIXTURES / "flow_invoices.json").read_text(encoding="utf-8"))
    data = copy.deepcopy(data)
    if change is not None:
        change(data)
    return Spec.model_validate(data)


def codes(spec: Spec) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in validate(spec)}


def machine(data: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = data["state_machines"][0]
    return result


def test_the_example_is_valid() -> None:
    assert validate(spec_with()) == []


def test_unknown_entity_and_duplicate_machine() -> None:
    assert ("state_machines[0].entity", "unknown_entity") in codes(
        spec_with(lambda d: machine(d).update(entity="Nope"))
    )
    assert ("state_machines[1].entity", "duplicate") in codes(
        spec_with(lambda d: d["state_machines"].append(copy.deepcopy(machine(d))))
    )


def test_the_state_field_must_be_a_required_enum_with_the_initial_state() -> None:
    assert ("state_machines[0].field", "invalid_value") in codes(
        spec_with(lambda d: machine(d).update(field="amount"))
    )
    assert ("state_machines[0].initial", "unknown_state") in codes(
        spec_with(lambda d: machine(d).update(initial="ghost"))
    )

    def optional(d: dict[str, Any]) -> None:
        d["entities"][0]["fields"][3]["required"] = False

    assert ("state_machines[0].field", "invalid_value") in codes(spec_with(optional))


def test_transitions_must_name_known_states_and_be_unique() -> None:
    def bad(d: dict[str, Any]) -> None:
        t = machine(d)["transitions"]
        t[0]["to_state"] = "ghost"
        t[1]["from_states"] = []
        t[2]["name"] = "submit"
        t[3]["name"] = "Bad Name"

    found = codes(spec_with(bad))
    assert ("state_machines[0].transitions[0].to_state", "unknown_state") in found
    assert ("state_machines[0].transitions[1].from_states", "required") in found
    assert ("state_machines[0].transitions[2].name", "duplicate_name") in found
    assert ("state_machines[0].transitions[3].name", "invalid_value") in found


def test_guards_are_checked_with_the_expression_engine() -> None:
    def bad(d: dict[str, Any]) -> None:
        t = machine(d)["transitions"]
        t[1]["when"] = "amount +"  # does not parse
        t[2]["when"] = "ghost_field > 1"  # unknown field
        t[3]["when"] = "amount + 1"  # not true/false
        t[4]["when"] = "eval('1')"  # not a function

    found = codes(spec_with(bad))
    for i in (1, 2, 3, 4):
        assert (f"state_machines[0].transitions[{i}].when", "invalid_expression") in found


def test_roles_must_exist_and_automatic_moves_have_none() -> None:
    def bad(d: dict[str, Any]) -> None:
        t = machine(d)["transitions"]
        t[0]["roles"] = ["ghost"]
        t[1]["roles"] = ["admin"]  # automatic

    found = codes(spec_with(bad))
    assert ("state_machines[0].transitions[0].roles[0]", "unknown_role") in found
    assert ("state_machines[0].transitions[1].roles", "invalid_value") in found

    def no_auth(d: dict[str, Any]) -> None:
        del d["auth"]

    assert ("state_machines[0].transitions[0].roles", "auth_required") in codes(spec_with(no_auth))


def test_automatic_loops_are_refused() -> None:
    def loop(d: dict[str, Any]) -> None:
        m = machine(d)
        m["transitions"] += [
            {"name": "back", "from_states": ["approved"], "to_state": "submitted", "auto": True}
        ]

    assert ("state_machines[0].transitions", "auto_cycle") in codes(spec_with(loop))


def test_a_guard_that_is_too_long_is_refused_without_parsing() -> None:
    def long(d: dict[str, Any]) -> None:
        machine(d)["transitions"][0]["when"] = "amount > 1 and " * 100 + "true"

    assert ("state_machines[0].transitions[0].when", "too_long") in codes(spec_with(long))
