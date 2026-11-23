"""CP-6B: the `regulated` spec block (D40 regulated mode, D41 field protection, D43 customer-managed
keys): every validation code, and the spec hash of a spec without the block."""

import copy
import json
from pathlib import Path
from typing import Any

from app.core.spec_models import Spec, spec_hash
from app.core.validation import validate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _data() -> dict[str, Any]:
    data: dict[str, Any] = copy.deepcopy(json.loads((FIXTURES / "api_edge_orders.json").read_text(encoding="utf-8")))
    return data


def _codes(data: dict[str, Any]) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in validate(Spec.model_validate(data))}


def _reg(data: dict[str, Any], *fields: dict[str, Any], **block: Any) -> dict[str, Any]:
    data["regulated"] = {"enabled": True, "key_provider": "file", "fields": list(fields), **block}
    return data


def _f(entity: str = "Customer", field: str = "email", **kw: Any) -> dict[str, Any]:
    return {"entity": entity, "field": field, **kw}


def test_a_valid_block_has_no_issue() -> None:
    assert _codes(_reg(_data(), _f(), _f(field="name", mode="tokenise"))) == set()


def test_spec_hash_is_unchanged_without_the_block() -> None:
    spec = Spec.model_validate(_data())
    assert spec.regulated is None
    dump = spec.model_dump(mode="json")
    dump.pop("regulated")
    dump.pop("packs")
    dump.pop("compliance")
    dump.pop("api_platform")
    import hashlib

    canonical = json.dumps(dump, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert spec_hash(spec) == hashlib.sha256(canonical.encode("ascii")).hexdigest()
    with_block = Spec.model_validate(_reg(_data(), _f()))
    assert spec_hash(with_block) != spec_hash(spec)


def test_too_many() -> None:
    fields = [_f(field=f"f{i}") for i in range(65)]
    assert ("regulated.fields", "too_many") in _codes(_reg(_data(), *fields))


def test_unknown_entity() -> None:
    assert ("regulated.fields[0].entity", "unknown_entity") in _codes(_reg(_data(), _f(entity="Nope")))


def test_unknown_field() -> None:
    assert ("regulated.fields[0].field", "unknown_field") in _codes(_reg(_data(), _f(field="nope")))


def test_duplicate_field() -> None:
    assert ("regulated.fields[1]", "duplicate_field") in _codes(_reg(_data(), _f(), _f()))


def test_type_not_supported() -> None:
    got = _codes(_reg(_data(), _f(entity="Order", field="total")))
    assert ("regulated.fields[0].field", "type_not_supported") in got


def test_encrypted_unique() -> None:
    data = _data()
    data["entities"][0]["fields"][1]["unique"] = True
    assert ("regulated.fields[0].field", "encrypted_unique") in _codes(_reg(data, _f()))
    data = _data()
    data["entities"][0]["fields"][1]["indexed"] = True
    assert ("regulated.fields[0].field", "encrypted_unique") in _codes(_reg(data, _f()))


def test_searchable_needs_encrypt() -> None:
    got = _codes(_reg(_data(), _f(mode="tokenise", searchable=True)))
    assert ("regulated.fields[0].searchable", "searchable_needs_encrypt") in got


def test_regulated_needs_cmk() -> None:
    assert ("regulated.key_provider", "regulated_needs_cmk") in _codes(_reg(_data(), _f(), key_provider="env"))
    # a disabled block is not checked for the key
    assert ("regulated.key_provider", "regulated_needs_cmk") not in _codes(
        _reg(_data(), _f(), key_provider="env", enabled=False)
    )


def test_regulated_needs_auth() -> None:
    data = _data()
    data.pop("auth")
    assert ("regulated", "regulated_needs_auth") in _codes(_reg(data, _f()))


def test_encrypted_field_in_entity_options() -> None:
    data = _data()
    data["entities"][0]["options"].update(sortable=["email"], searchable=["email"], filterable=["email"])
    got = _codes(_reg(data, _f()))
    for key in ("sortable", "searchable", "filterable"):
        assert (f"entities[Customer].options.{key}", "encrypted_field_used") in got


def test_searchable_field_may_be_filtered_by_equality() -> None:
    data = _data()
    data["entities"][0]["options"]["filterable"] = ["email"]
    got = _codes(_reg(data, _f(searchable=True)))
    assert ("entities[Customer].options.filterable", "encrypted_field_used") not in got


def test_encrypted_field_in_state_machine_guard() -> None:
    data = _data()
    data["state_machines"] = [
        {
            "entity": "Order",
            "field": "status",
            "initial": "new",
            "transitions": [{"name": "go", "from_states": ["new"], "to_state": "paid", "when": "reference == 'x'"}],
        }
    ]
    states = data["entities"][1]["fields"][2].get("enum_values") or ["new", "paid"]
    data["entities"][1]["fields"][2]["enum_values"] = list({*states, "new", "paid"})
    data["entities"][1]["fields"][2]["required"] = True
    got = _codes(_reg(data, _f(entity="Order", field="reference")))
    assert ("state_machines[0].transitions[0].when", "encrypted_field_used") in got


def test_encrypted_field_in_sequence() -> None:
    data = _data()
    data["sequences"] = [{"name": "ref", "entity": "Order", "field": "reference"}]
    got = _codes(_reg(data, _f(entity="Order", field="reference")))
    assert ("sequences[0].field", "encrypted_field_used") in got


def test_encrypted_field_in_history() -> None:
    data = _data()
    data["history"] = [{"entity": "Customer", "fields": ["email"], "retention_days": 30}]
    assert ("history[0].fields", "encrypted_field_used") in _codes(_reg(data, _f()))


def test_encrypted_field_in_seed() -> None:
    data = _data()
    data["seed"] = [
        {
            "name": "demo",
            "seed": 1,
            "as_of": "2026-01-01",
            "entities": [
                {
                    "entity": "Customer",
                    "count": 2,
                    "fields": [{"field": "email", "generator": {"type": "email", "prefix": "a"}}],
                }
            ],
        }
    ]
    got = _codes(_reg(data, _f()))
    assert ("seed[0].entities[0].fields[0]", "encrypted_field_used") in got


def test_encrypted_field_in_metrics() -> None:
    data = _data()
    data["metrics_layer"] = {
        "definitions": [
            {"key": "by_ref", "label": "By ref", "entity": "Order", "agg": "count", "group_by": "reference"}
        ]
    }
    got = _codes(_reg(data, _f(entity="Order", field="reference")))
    assert ("metrics_layer.definitions[0]", "encrypted_field_used") in got


def test_encrypted_field_in_document_template() -> None:
    data = _data()
    data["documents"] = {
        "enabled": True,
        "templates": [
            {
                "id": "inv",
                "entity": "Customer",
                "roles": ["admin"],
                "template": {"blocks": [{"type": "text", "text": "{{row.email}}"}]},
            }
        ],
    }
    got = _codes(_reg(data, _f()))
    assert ("documents.templates[0].template", "encrypted_field_used") in got


def test_encrypted_field_in_hook_field_list() -> None:
    data = _data()
    data["hooks"] = [
        {
            "name": "tidy",
            "point": "Customer.before_save",
            "input": {"name": "In", "fields": [{"name": "email", "type": "string"}]},
            "output": {"name": "Out", "fields": [{"name": "name", "type": "string"}]},
        }
    ]
    assert ("hooks[0].input.fields[0]", "encrypted_field_used") in _codes(_reg(data, _f()))


def test_the_block_is_scanned_for_secrets() -> None:
    data = _reg(_data(), _f())
    data["regulated"]["fields"][0]["entity"] = "sk_" "live_abcdefghijklmnopqrstuvwx"
    assert any(code == "secret_in_spec" for _, code in _codes(data))


def test_encrypted_field_in_an_agent_entity_create_action() -> None:
    """An agent proposal stores the payload it would insert in a plaintext table, so a protected field cannot be in
    an entity_create allow-list."""
    data = copy.deepcopy(json.loads((FIXTURES / "ai_agents_evals.json").read_text(encoding="utf-8")))
    actions = data["packs"]["ai"]["agents"]["actions"]
    index = next(i for i, a in enumerate(actions) if a["kind"] == "entity_create")
    assert not any(code == "encrypted_field_used" for _, code in _codes(data))
    data["regulated"] = {"enabled": True, "key_provider": "file", "fields": [{"entity": "Ticket", "field": "title"}]}
    assert (f"packs.ai.agents.actions[{index}].fields", "encrypted_field_used") in _codes(data)


def test_compose_wires_the_key_file_and_silences_the_access_log() -> None:
    """SENTINEL CP-6B: the key file is mounted read-only into every service that runs app code, the server access log
    (which prints the query string of a blind-index filter) is off, and the provider vault key is optional."""
    import yaml

    from app.core.generator.engine import generate

    spec = Spec.model_validate_json((FIXTURES / "regulated_clients.json").read_text(encoding="utf-8"))
    compose = yaml.safe_load(generate(spec)["docker-compose.yml"])
    app_services = {n: s for n, s in compose["services"].items() if s.get("build") == "."}
    assert "api" in app_services and len(app_services) >= 2
    for name, service in app_services.items():
        assert service["environment"]["REGULATED_KEY_FILE"] == "/run/secrets/regulated.keys", name
        assert any(v.endswith(":/run/secrets/regulated.keys:ro") for v in service["volumes"]), name
    api = compose["services"]["api"]["environment"]
    assert api["UVICORN_ACCESS_LOG"] == "false"
    assert "?" not in api["PROVIDER_VAULT_KEY"]
