"""Seed-plan validation: the plan is closed, so every way it can be wrong has a path and a code."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.generator import generate
from app.core.generator.context import build_context
from app.core.spec_models import Spec
from app.core.validation import validate
from app.core.validation_seed import tenant_scoped

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def spec_with(change: Any = None, name: str = "seed_demo") -> Spec:
    data: dict[str, Any] = copy.deepcopy(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))
    if change is not None:
        change(data)
    return Spec.model_validate(data)


def codes(spec: Spec) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in validate(spec)}


def field(d: dict[str, Any], entity: str, name: str, profile: int = 0) -> dict[str, Any]:
    plan = next(e for e in d["seed"][profile]["entities"] if e["entity"] == entity)
    return next(f for f in plan["fields"] if f["field"] == name)["generator"]


def test_the_example_is_valid_and_generates() -> None:
    spec = spec_with()
    assert validate(spec) == []
    assert "app/seed/runner.py" in generate(spec)


def test_the_tenant_rule_matches_the_generator_for_every_fixture() -> None:
    for path in sorted(FIXTURES.glob("*.json")):
        spec = Spec.model_validate_json(path.read_text(encoding="utf-8"))
        if validate(spec):
            continue
        ctx = build_context(spec)
        for e in ctx.entities:
            ours = tenant_scoped(spec, next(s for s in spec.entities if s.name == e.name))
            assert ours == e.tenant_scoped, (path.name, e.name)


def test_the_schema_forbids_unknown_keys() -> None:
    def bad(d: dict[str, Any]) -> None:
        field(d, "Invoice", "memo")["sql"] = "DROP TABLE invoices"

    with pytest.raises(ValidationError):
        spec_with(bad)

    def bad_profile(d: dict[str, Any]) -> None:
        d["seed"][0]["script"] = "x"

    with pytest.raises(ValidationError):
        spec_with(bad_profile)


def test_profiles_need_a_clean_name_seed_and_date() -> None:
    def bad(d: dict[str, Any]) -> None:
        d["seed"][0]["name"] = "Demo!"
        d["seed"][1]["name"] = "Demo!"
        d["seed"][0]["seed"] = -1
        d["seed"][0]["as_of"] = "2026-13-40"

    found = codes(spec_with(bad))
    assert ("seed[0].name", "invalid_value") in found
    assert ("seed[0].seed", "invalid_value") in found
    assert ("seed[0].as_of", "invalid_value") in found

    def dup(d: dict[str, Any]) -> None:
        d["seed"][1]["name"] = "demo"

    assert ("seed[1].name", "duplicate_name") in codes(spec_with(dup))


def test_counts_and_tenants_stay_under_the_ceilings() -> None:
    def bad(d: dict[str, Any]) -> None:
        d["seed"][0]["entities"][0]["count"] = 10_001
        d["seed"][0]["entities"][1]["count"] = -1
        d["seed"][1]["tenants"] = 21
        d["seed"][1]["entities"][1]["count"] = 4000  # 4000 x 3 tenants = 12000 rows

    found = codes(spec_with(bad))
    assert ("seed[0].entities[0].count", "invalid_value") in found
    assert ("seed[0].entities[1].count", "invalid_value") in found
    assert ("seed[1].tenants", "invalid_value") in found
    d_ok = spec_with(lambda d: d["seed"][1].__setitem__("tenants", 3))

    def many(d: dict[str, Any]) -> None:
        d["seed"][1]["entities"][1]["count"] = 4000

    assert ("seed[1].entities[1].count", "too_many_rows") in codes(spec_with(many))
    assert validate(d_ok) == []


def test_tenants_only_for_multi_tenant_projects_and_scoped_entities_need_them() -> None:
    def single(d: dict[str, Any]) -> None:
        d["auth"]["multi_tenant"] = False
        d["auth"]["permissions"] = []

    assert ("seed[0].tenants", "tenants_not_supported") in codes(spec_with(single))

    def none(d: dict[str, Any]) -> None:
        d["seed"][0]["tenants"] = 0

    assert ("seed[0].entities[0].entity", "tenants_required") in codes(spec_with(none))


def test_entities_and_fields_must_exist() -> None:
    def bad(d: dict[str, Any]) -> None:
        d["seed"][0]["entities"][0]["entity"] = "Ghost"
        d["seed"][0]["entities"][1]["fields"].append(
            {"field": "tenant_id", "generator": {"type": "constant", "value": "x"}}
        )
        d["seed"][0]["entities"][1]["fields"].append(
            {"field": "memo", "generator": {"type": "constant", "value": "x"}}
        )

    found = codes(spec_with(bad))
    assert ("seed[0].entities[0].entity", "unknown_entity") in found
    assert ("seed[0].entities[1].fields[6].field", "unknown_field") in found  # ids, tenant, owner: platform only
    assert ("seed[0].entities[1].fields[7].field", "duplicate") in found


@pytest.mark.parametrize(
    ("entity", "name", "generator", "code"),
    [
        ("Invoice", "memo", {"type": "bool_ratio", "ratio": 0.5}, "type_mismatch"),
        ("Invoice", "memo", {"type": "shell"}, "unknown_generator"),
        ("Invoice", "memo", {"type": "one_of", "values": ["a"], "prefix": "x"}, "unexpected_key"),
        ("Invoice", "memo", {"type": "one_of", "values": [1]}, "invalid_value"),
        ("Invoice", "memo", {"type": "one_of", "values": []}, "required"),
        ("Invoice", "memo", {"type": "constant", "value": "x" * 201}, "invalid_value"),
        ("Invoice", "memo", {"type": "constant", "value": "a@gmail.com"}, "invalid_value"),
        ("Invoice", "amount", {"type": "int_range", "min": 1, "max": 5}, "type_mismatch"),
        ("Invoice", "amount", {"type": "decimal_range", "min": "5", "max": "1", "places": 2}, "invalid_range"),
        ("Invoice", "amount", {"type": "decimal_range", "min": "-5", "max": "10", "places": 2}, "invalid_value"),
        ("Invoice", "amount", {"type": "decimal_range", "min": "1.555", "max": "9", "places": 2}, "invalid_value"),
        ("Invoice", "amount", {"type": "decimal_range", "min": "1", "max": "9", "places": 9}, "invalid_value"),
        ("Invoice", "issued_on", {"type": "date_range", "min": "2026-05-01", "max": "2026-01-01"}, "invalid_range"),
        ("Invoice", "issued_on", {"type": "date_range", "min": "soon", "max": "2026-01-01"}, "required"),
        ("Invoice", "invoice_no", {"type": "one_of", "values": ["a", "b"]}, "unique_not_injective"),
        ("Invoice", "invoice_no", {"type": "sequence", "prefix": "INV-" + "x" * 40}, "invalid_value"),
        ("Invoice", "invoice_no", {"type": "sequence", "prefix": "a b"}, "invalid_value"),
        ("Invoice", "invoice_no", {"type": "sequence", "prefix": "P" * 35, "width": 12}, "too_long"),
        ("Invoice", "status", {"type": "constant", "value": "paid"}, "state_managed"),
        ("Invoice", "memo", {"type": "state", "weights": {"draft": 1}}, "invalid_generator"),
        ("Invoice", "memo", {"type": "reference", "entity": "Customer"}, "invalid_generator"),
        ("Invoice", "status", {"type": "state", "weights": {"nope": 1}}, "unknown_state"),
        ("Invoice", "status", {"type": "state", "weights": {"draft": 0}}, "invalid_value"),
        ("Invoice", "status", {"type": "state", "weights": {"draft": -1, "paid": 1}}, "invalid_value"),
        ("Customer", "active", {"type": "bool_ratio", "ratio": 1.5}, "invalid_value"),
        ("Customer", "name", {"type": "words", "min_words": 3, "max_words": 2}, "invalid_value"),
        ("Customer", "name", {"type": "words", "min_words": 1, "max_words": 20}, "too_long"),
        ("Customer", "email", {"type": "email", "prefix": "Bad Prefix"}, "invalid_value"),
        ("Customer", "email", {"type": "words", "min_words": 1, "max_words": 2}, "unique_not_injective"),
    ],
)
def test_each_generator_checks_its_keys_and_values(
    entity: str, name: str, generator: dict[str, Any], code: str
) -> None:
    def change(d: dict[str, Any]) -> None:
        plan = next(e for e in d["seed"][0]["entities"] if e["entity"] == entity)
        for f in plan["fields"]:
            if f["field"] == name:
                f["generator"] = generator

    found = {c for (_p, c) in codes(spec_with(change))}
    assert code in found, found


def test_required_columns_and_foreign_keys_must_be_filled() -> None:
    def bad(d: dict[str, Any]) -> None:
        plan = d["seed"][0]["entities"][1]
        plan["fields"] = [f for f in plan["fields"] if f["field"] not in ("amount", "customer_id")]

    found = [i.message for i in validate(spec_with(bad)) if i.code == "required_field_missing"]
    assert any("Invoice.amount" in m for m in found)
    assert any("Invoice.customer_id" in m for m in found)


def test_secret_looking_columns_are_not_seeded() -> None:
    def bad(d: dict[str, Any]) -> None:
        d["entities"][0]["fields"].append({"name": "api_token", "type": "string"})
        plan = d["seed"][0]["entities"][0]
        plan["fields"].append({"field": "api_token", "generator": {"type": "constant", "value": "abc"}})

    assert any(c == "secret_name" for (_p, c) in codes(spec_with(bad)))


def test_json_and_file_columns_cannot_be_seeded() -> None:
    def bad(d: dict[str, Any]) -> None:
        d["entities"][0]["fields"].append({"name": "extra", "type": "json"})
        plan = d["seed"][0]["entities"][0]
        plan["fields"].append({"field": "extra", "generator": {"type": "constant", "value": "x"}})

    assert any(c == "unsupported_field_type" for (_p, c) in codes(spec_with(bad)))


def test_references_must_match_the_relation_be_seeded_and_not_loop() -> None:
    def other_entity(d: dict[str, Any]) -> None:
        field(d, "Invoice", "customer_id")["entity"] = "Invoice"

    assert any(c in ("type_mismatch", "self_reference") for (_p, c) in codes(spec_with(other_entity)))

    def not_seeded(d: dict[str, Any]) -> None:
        d["seed"][0]["entities"] = [e for e in d["seed"][0]["entities"] if e["entity"] != "Customer"]

    assert any(c == "reference_not_seeded" for (_p, c) in codes(spec_with(not_seeded)))

    def empty(d: dict[str, Any]) -> None:
        d["seed"][0]["entities"][0]["count"] = 0

    assert any(c == "empty_reference" for (_p, c) in codes(spec_with(empty)))

    def pick(d: dict[str, Any]) -> None:
        field(d, "Invoice", "customer_id")["pick"] = "newest"

    assert ("seed[0].entities[1].fields[4].generator.pick", "invalid_value") in codes(spec_with(pick))

    def wrong_column(d: dict[str, Any]) -> None:
        field(d, "Invoice", "customer_id").update({"type": "constant", "value": "x", "entity": None})

    assert any(c == "type_mismatch" for (_p, c) in codes(spec_with(wrong_column)))


def test_a_reference_loop_is_refused() -> None:
    def loop(d: dict[str, Any]) -> None:
        d["entities"].append(
            {"name": "Note", "table_name": "notes", "plural_path": "notes", "fields": [{"name": "t", "type": "string"}]}
        )
        d["relations"].append(
            {"kind": "one_to_many", "from_entity": "Invoice", "to_entity": "Note", "from_name": "notes", "to_name": "invoice"}
        )
        d["relations"].append(
            {"kind": "one_to_many", "from_entity": "Note", "to_entity": "Invoice", "from_name": "invs", "to_name": "note"}
        )
        d["auth"]["permissions"].append({"entity": "Note", "operation": "list", "roles": ["admin"], "row_rule": "tenant"})
        plan = d["seed"][0]["entities"]
        plan.append(
            {"entity": "Note", "count": 1, "fields": [{"field": "invoice_id", "generator": {"type": "reference", "entity": "Invoice"}}]}
        )
        next(e for e in plan if e["entity"] == "Invoice")["fields"].append(
            {"field": "note_id", "generator": {"type": "reference", "entity": "Note"}}
        )

    assert any(c == "reference_cycle" for (_p, c) in codes(spec_with(loop)))


def test_a_unique_foreign_key_needs_an_injective_pick() -> None:
    def one_to_one(d: dict[str, Any]) -> None:
        d["relations"][0]["kind"] = "one_to_one"
        d["seed"][0]["entities"][1]["count"] = 8  # 8 invoices cannot each have one of 5 customers

    assert any(c == "unique_not_injective" for (_p, c) in codes(spec_with(one_to_one)))


def test_state_weights_need_reachable_states() -> None:
    def unreachable(d: dict[str, Any]) -> None:
        d["state_machines"][0]["transitions"] = [
            t for t in d["state_machines"][0]["transitions"] if t["to_state"] != "paid"
        ]

    assert any(c == "unreachable_state" for (_p, c) in codes(spec_with(unreachable)))


def test_the_seed_table_name_is_reserved() -> None:
    def clash(d: dict[str, Any]) -> None:
        d["entities"][0]["table_name"] = "seed_rows"

    assert any("seed_rows" in i.message for i in validate(spec_with(clash)))


def test_too_many_profiles() -> None:
    def many(d: dict[str, Any]) -> None:
        d["seed"] = [{**copy.deepcopy(d["seed"][0]), "name": f"p{i}"} for i in range(6)]

    assert ("seed", "too_many") in codes(spec_with(many))
