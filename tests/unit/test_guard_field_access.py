"""A transition guard must not reveal a field the caller cannot read (CP-4F1 fix MED-1): the validation rule
`guard_reads_hidden_field`, and the generated transition routes that hide the guard from such callers."""

import json
from pathlib import Path

import pytest

from app.core.generator import generate
from app.core.spec_models import Spec
from app.core.validation import validate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"
CODE = "guard_reads_hidden_field"


def _spec() -> Spec:
    return Spec.model_validate(json.loads((FIXTURES / "field_access.json").read_text(encoding="utf-8")))


def _codes(spec: Spec) -> list[str]:
    return [i.code for i in validate(spec)]


def _set(spec: Spec, index: int, **changes: object) -> Spec:
    transition = spec.state_machines[0].transitions[index]
    for key, value in changes.items():
        setattr(transition, key, value)
    return spec


def test_the_example_is_valid_because_every_performer_can_read_salary() -> None:
    spec = _spec()
    assert CODE not in _codes(spec)


def test_a_guard_over_a_restricted_field_open_to_anyone_who_may_update_is_refused() -> None:
    spec = _set(_spec(), 1, when="salary > 100")  # `archive` has no roles: staff may update, staff cannot read salary
    issues = [i for i in validate(spec) if i.code == CODE]
    assert len(issues) == 1 and issues[0].path == "state_machines[0].transitions[1].when"
    assert "Employee.salary" in issues[0].message and "staff" in issues[0].message


def test_a_role_that_cannot_read_the_field_is_refused_even_when_listed() -> None:
    assert CODE in _codes(_set(_spec(), 0, roles=["hr", "staff"]))
    assert CODE not in _codes(_set(_spec(), 0, roles=["admin"]))  # admin reads salary


def test_inheritance_counts_for_the_performer() -> None:
    spec = _spec()
    _set(spec, 0, when="notes != 'x'", roles=["admin"])
    assert CODE not in _codes(spec)  # admin holds hr, which reads notes


def test_an_automatic_transition_is_judged_by_everyone_who_can_read_the_record() -> None:
    spec = _spec()
    _set(spec, 1, when="salary > 100", auto=True)
    assert CODE in _codes(spec)  # staff can read the row and would see the state change


def test_a_guard_over_unrestricted_fields_or_without_rules_is_never_refused() -> None:
    spec = _spec()
    assert spec.authorization is not None
    assert CODE not in _codes(_set(spec, 1, when="name != 'x'"))
    spec.authorization.field_access = []
    assert CODE not in _codes(_set(spec, 1, when="salary > 100"))
    assert CODE not in _codes(_set(_spec(), 1, when=None))


@pytest.mark.parametrize("when", ["salary > 1 and name != 'a'", "not (salary < 3)", "coalesce(salary, 0) > 3"])
def test_the_field_is_found_anywhere_in_the_expression(when: str) -> None:
    assert CODE in _codes(_set(_spec(), 1, when=when))


def test_the_generated_routes_hide_the_guard_from_callers_with_hidden_fields() -> None:
    files = generate(_spec())
    router = files["app/state_machines/router.py"]
    assert router.count('mask_guard=bool(_fx.hidden_read("Employee", access.user))') == 2
    engine = files["app/state_machines/engine.py"]
    assert "GENERIC_REASON" in engine and "is not available" in engine
    # a project without field rules is unchanged by the mask
    spec = _spec()
    assert spec.authorization is not None
    spec.authorization.field_access = []
    assert "mask_guard=bool" not in generate(spec)["app/state_machines/router.py"]
