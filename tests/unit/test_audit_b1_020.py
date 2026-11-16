"""Audit B1-020: validation gaps (F-0166 .. F-0172)."""

import json
from pathlib import Path
from typing import Any

from app.core.spec_models import Spec
from app.core.validation import validate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _fx(name: str = "ai_agents_evals.json") -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _codes(d: dict[str, Any]) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in validate(Spec.model_validate(d))}


def _only_codes(d: dict[str, Any]) -> set[str]:
    return {c for _, c in _codes(d)}


def _ai_ticket(list_fields: list[str]) -> dict[str, Any]:
    d = _fx()
    t = d["entities"][0]
    t["fields"] += [
        {"name": "status", "type": "enum", "required": True, "enum_values": ["open", "closed"]},
        {"name": "ref", "type": "string", "required": True, "unique": True, "max_length": 40},
    ]
    d["state_machines"] = [
        {"entity": "Ticket", "field": "status", "initial": "open", "transitions": [{"name": "close", "from_states": ["open"], "to_state": "closed", "roles": ["admin"]}]}
    ]
    d["sequences"] = [{"name": "ticket_no", "prefix": "T-", "entity": "Ticket", "field": "ref"}]
    d["authorization"] = {"model": "rbac", "field_access": [{"entity": "Ticket", "field": "priority", "write_roles": ["admin"]}]}
    for a in d["packs"]["ai"]["agents"]["actions"]:
        if a["name"] == "open_ticket":
            a["fields"] = list_fields
    return d


def test_f0166_ai_cannot_allow_list_state_numbered_or_field_access_fields() -> None:
    for f in ("status", "ref"):
        assert "protected_field" in _only_codes(_ai_ticket(["title", f]))
    assert "protected_field" in _only_codes(_ai_ticket(["title", "priority"]))
    # a required state/numbered field with no default can never be filled by an agent insert: the entity is refused
    assert "required_field_missing" in _only_codes(_ai_ticket(["title"]))


def test_f0171_ai_refuses_entity_with_required_fk() -> None:
    d = _fx()
    d["entities"].append({"name": "Customer", "table_name": "customers", "plural_path": "customers", "fields": [{"name": "name", "type": "string", "required": True}]})
    d["relations"] = [{"kind": "one_to_many", "from_entity": "Customer", "to_entity": "Ticket", "from_name": "tickets", "to_name": "customer", "required": True}]
    assert "required_relation_missing" in _only_codes(d)
    d["relations"][0]["required"] = False
    assert "required_relation_missing" not in _only_codes(d)


def _table_issue(d: dict[str, Any], table: str) -> bool:
    d["entities"][0]["table_name"] = table
    return any(c == "duplicate_name" and p == "entities[0].table_name" for p, c in _codes(d))


def test_f0167_module_tables_are_claimed() -> None:
    for t in ("invoices", "invoice_lines", "invoice_counters", "invoice_payments", "money_payouts", "reconciliation_runs", "reconciliation_events"):
        assert _table_issue(_fx("money_marketplace.json"), t), t
    assert _table_issue(_fx("demo_invoice.json"), "state_transitions")


def test_f0168_entity_path_cannot_shadow_a_module_prefix() -> None:
    d = _ai_ticket(["title"])  # sequences -> config module; the fixture also has auth and the ai pack
    for path in ("auth", "config", "ai"):
        d["entities"][0]["plural_path"] = path
        assert ("entities[0].plural_path", "reserved_word") in _codes(d) or ("entities[0].plural_path", "duplicate_name") in _codes(d), path
    # an inactive module does not reserve its prefix
    d = _fx("blog.json")
    d["entities"][0]["plural_path"] = "providers"
    assert not any(p == "entities[0].plural_path" for p, _ in _codes(d))


def test_f0169_seed_one_to_one_from_scoped_child_to_shared_parent_is_injective() -> None:
    from app.core import seed_engine as eng
    from app.core.generator.context import build_context
    from app.core.generator.features.seed import module as sm

    d = _fx()
    d.pop("packs")
    d["entities"] = [
        {"name": "Plan", "table_name": "plans", "plural_path": "plans", "fields": [{"name": "title", "type": "string", "required": True}]},
        {"name": "Seat", "table_name": "seats", "plural_path": "seats", "fields": [{"name": "label", "type": "string", "required": True}]},
    ]
    d["relations"] = [{"kind": "one_to_one", "from_entity": "Plan", "to_entity": "Seat", "from_name": "seat", "to_name": "plan", "required": True}]
    d["auth"]["permissions"] = [{"entity": "Seat", "operation": "list", "roles": ["admin"], "row_rule": "tenant"}]
    d["seed"] = [
        {
            "name": "demo", "seed": 1, "as_of": "2026-01-01", "tenants": 2,
            "entities": [
                {"entity": "Plan", "count": 2, "fields": [{"field": "title", "generator": {"type": "constant", "value": "p"}}]},
                {"entity": "Seat", "count": 1, "fields": [
                    {"field": "label", "generator": {"type": "constant", "value": "s"}},
                    {"field": "plan_id", "generator": {"type": "reference", "entity": "Plan", "pick": "cycle"}},
                ]},
            ],
        }
    ]
    spec = Spec.model_validate(d)
    assert not validate(spec)
    ctx = build_context(spec)
    data = eng.generate(sm.definitions(ctx), json.loads(json.dumps(spec.seed[0].model_dump(mode="json"))))
    plan_ids = [r.values["plan_id"] for r in data.rows if r.table == "seats"]
    assert len(plan_ids) == 2 and len(set(plan_ids)) == 2


def test_f0170_numbered_string_length_counts_the_start_value() -> None:
    d = _fx()
    d.pop("packs")
    d["entities"][0]["fields"].append({"name": "ref", "type": "string", "required": True, "unique": True, "max_length": 13})
    d["sequences"] = [{"name": "ticket_no", "prefix": "INV-", "start": 10**12, "entity": "Ticket", "field": "ref"}]
    assert ("sequences[0].field", "sequence_field") in _codes(d)
    d["sequences"][0]["start"] = 1
    assert ("sequences[0].field", "sequence_field") not in _codes(d)


def test_f0172_secret_values_in_settings_lists_seed_and_documents_are_found() -> None:
    fake = "sk_" "live_" "a1B2c3D4e5F6g7H8i9J0"
    d = _fx()
    d.pop("packs")
    d["settings"] = [{"key": "stripe_account", "type": "string", "default": fake}]
    assert ("settings[0].default", "secret_in_spec") in _codes(d)
    d["settings"] = []
    d["lists"] = [{"name": "keys", "items": [{"value": fake, "label": "x"}]}]
    assert any(c == "secret_in_spec" and p.startswith("lists[0]") for p, c in _codes(d))
