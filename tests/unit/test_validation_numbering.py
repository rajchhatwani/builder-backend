"""Numbered fields (`sequences[].entity/field`): every way the binding can be wrong is reported with a path and a
code, a valid binding makes the field platform-managed, and the seed plan may not set a numbered field."""

import copy
import json
from pathlib import Path
from typing import Any

from app.core.generator import generate
from app.core.generator.context import build_context
from app.core.spec_models import Spec
from app.core.validation import validate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def spec_with(change: Any = None, name: str = "numbering") -> Spec:
    data: dict[str, Any] = copy.deepcopy(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))
    if change is not None:
        change(data)
    return Spec.model_validate(data)


def codes(spec: Spec) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in validate(spec)}


def order_field(d: dict[str, Any], name: str) -> dict[str, Any]:
    return next(f for f in d["entities"][0]["fields"] if f["name"] == name)


def sequence(d: dict[str, Any], name: str) -> dict[str, Any]:
    return next(q for q in d["sequences"] if q["name"] == name)


def test_the_example_is_valid_and_its_numbered_fields_are_platform_managed() -> None:
    spec = spec_with()
    assert validate(spec) == []
    order = build_context(spec).entity_by_name["Order"]
    assert {n[0] for n in order.numbered} == {"invoice_no", "order_no", "ticket_no"}
    assert all(f.managed and not f.patchable for f in order.fields if f.name in {n[0] for n in order.numbered})
    files = generate(spec)
    # not writable: the create and update schemas have no numbered field
    schemas = files["app/schemas/orders.py"]
    assert "invoice_no" not in schemas.split("class OrderUpdate")[0].split("class OrderCreate")[1]
    assert "invoice_no" not in schemas.split("class OrderRead")[0].split("class OrderUpdate")[1]
    assert "invoice_no" in schemas.split("class OrderRead")[1]
    assert "app/runtime_config/numbering.py" in files and "tests/test_numbering.py" in files


def test_a_binding_needs_both_halves_and_real_names() -> None:
    def half(d: dict[str, Any]) -> None:
        del sequence(d, "invoice_no")["field"]

    assert ("sequences[0]", "sequence_binding") in codes(spec_with(half))

    def ghosts(d: dict[str, Any]) -> None:
        sequence(d, "invoice_no")["entity"] = "Ghost"
        sequence(d, "order_no")["field"] = "nope"

    found = codes(spec_with(ghosts))
    assert ("sequences[0].entity", "unknown_entity") in found
    assert ("sequences[1].field", "unknown_field") in found


def test_a_field_is_numbered_by_one_sequence_only() -> None:
    def bad(d: dict[str, Any]) -> None:
        sequence(d, "order_no")["field"] = "invoice_no"

    assert any(code == "field_in_use" for _, code in codes(spec_with(bad)))


def test_the_field_must_be_a_unique_required_string_or_bigint_without_default() -> None:
    def bad(d: dict[str, Any]) -> None:
        f = order_field(d, "invoice_no")
        f["unique"] = False
        f["required"] = False
        f["default"] = "X"

    messages = " | ".join(i.message for i in validate(spec_with(bad)) if i.code == "sequence_field")
    assert "must be unique" in messages and "must be required" in messages and "cannot have a default" in messages

    def wrong_type(d: dict[str, Any]) -> None:
        order_field(d, "invoice_no").update(type="integer", max_length=None)

    assert any("not integer" in i.message for i in validate(spec_with(wrong_type)) if i.code == "sequence_field")


def test_a_bigint_field_needs_a_bare_counter_and_a_string_field_needs_room() -> None:
    def prefixed_counter_in_a_number(d: dict[str, Any]) -> None:
        sequence(d, "invoice_no")["field"] = "ticket_no"  # INV-00001 does not fit a bigint
        sequence(d, "ticket_no")["field"] = "invoice_no"  # and a bare counter in a string is fine

    found = [i for i in validate(spec_with(prefixed_counter_in_a_number)) if i.code == "sequence_field"]
    assert len(found) == 1 and "use a string field" in found[0].message

    def too_short(d: dict[str, Any]) -> None:
        order_field(d, "order_no")["max_length"] = 10  # ORD-2026-0001 plus a growing counter

    assert any("raise max_length" in i.message for i in validate(spec_with(too_short)))


def test_a_per_tenant_sequence_is_refused_because_unique_is_table_wide() -> None:
    def bad(d: dict[str, Any]) -> None:
        sequence(d, "invoice_no")["per_tenant"] = True

    assert any(code == "per_tenant_unsupported" for _, code in codes(spec_with(bad)))


def test_the_state_of_a_state_machine_cannot_be_numbered() -> None:
    def bad(d: dict[str, Any]) -> None:
        sequence(d, "ticket_no")["field"] = "stage"

    assert any("state of a state machine" in i.message for i in validate(spec_with(bad)))


def test_the_seed_plan_may_not_set_a_numbered_field_and_need_not_fill_it() -> None:
    assert validate(spec_with()) == []  # the example's seed plan leaves all three numbered fields out

    def bad(d: dict[str, Any]) -> None:
        order = d["seed"][0]["entities"][0]
        order["fields"].append(
            {"field": "invoice_no", "generator": {"type": "sequence", "prefix": "DEMO-", "start": 1, "width": 4}}
        )

    assert any(code == "sequence_numbered" for _, code in codes(spec_with(bad)))


def test_a_spec_without_numbered_fields_gets_none_of_the_machinery() -> None:
    files = generate(spec_with(name="runtime_config"))
    assert "app/runtime_config/numbering.py" not in files and "tests/test_numbering.py" not in files
    assert "numbered" not in files["app/crud/orders.py"]
