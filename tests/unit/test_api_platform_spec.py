"""CP-6D: the `api_platform` spec block (public API keys D49, installable apps D50): the good case, every refusal,
the generated files, and that a project without the block emits none of them."""

import copy
import json
from pathlib import Path
from typing import Any

from app.core.generator.engine import generate
from app.core.spec_models import Spec
from app.core.validation import validate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"
FILES = (
    "app/platform_api/__init__.py",
    "app/platform_api/models.py",
    "app/platform_api/service.py",
    "app/platform_api/router.py",
    "app/platform_api/public.py",
    "app/platform_api/events.py",
    "app/platform_api/settings.py",
    "alembic/versions/0045_api_platform.py",
    "tests/test_platform_api.py",
)


def _data() -> dict[str, Any]:
    data: dict[str, Any] = copy.deepcopy(json.loads((FIXTURES / "api_shop.json").read_text(encoding="utf-8")))
    return data


def _codes(data: dict[str, Any]) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in validate(Spec.model_validate(data))}


def _block(data: dict[str, Any], **changes: Any) -> dict[str, Any]:
    data["api_platform"].update(changes)
    return data


def test_the_fixture_is_valid() -> None:
    assert _codes(_data()) == set()


def test_a_disabled_block_needs_nothing() -> None:
    data = _data()
    data["api_platform"] = {"enabled": False}
    assert _codes(data) == set()


def test_enabled_needs_auth() -> None:
    data = _data()
    data.pop("auth")
    assert ("api_platform", "api_platform_needs_auth") in _codes(data)


def test_enabled_needs_roles_and_they_must_exist() -> None:
    assert ("api_platform.roles", "api_platform_needs_roles") in _codes(_block(_data(), roles=[]))
    assert ("api_platform.roles[0]", "unknown_role") in _codes(_block(_data(), roles=["ghost"]))


def test_enabled_needs_public_entities() -> None:
    assert ("api_platform.entities", "api_platform_needs_entities") in _codes(_block(_data(), entities=[]))


def test_rate_limits_are_parsed() -> None:
    assert ("api_platform.rate_limit", "invalid_rate_limit") in _codes(_block(_data(), rate_limit="fast"))
    assert ("api_platform.sandbox_rate_limit", "invalid_rate_limit") in _codes(_block(_data(), sandbox_rate_limit="0/minute"))
    assert _codes(_block(_data(), rate_limit="100/5minutes")) == set()


def test_public_entities_and_fields() -> None:
    data = _data()
    data["api_platform"]["entities"][0]["entity"] = "Ghost"
    assert ("api_platform.entities[0].entity", "unknown_entity") in _codes(data)
    data = _data()
    data["api_platform"]["entities"][1]["entity"] = "Product"
    assert ("api_platform.entities[1].entity", "duplicate_entity") in _codes(data)
    data = _data()
    data["api_platform"]["entities"][0]["fields"] = []
    assert ("api_platform.entities[0].fields", "public_entity_needs_fields") in _codes(data)
    data = _data()
    data["api_platform"]["entities"][0]["fields"] = ["title", "ghost"]
    assert ("api_platform.entities[0].fields[1]", "unknown_field") in _codes(data)
    data = _data()
    data["api_platform"]["entities"][0]["fields"] = ["title", "title"]
    assert ("api_platform.entities[0].fields", "duplicate_field") in _codes(data)


def test_secret_looking_fields_are_refused() -> None:
    data = _data()
    data["entities"][0]["fields"].append({"name": "api_token", "type": "string", "required": False, "max_length": 40})
    data["api_platform"]["entities"][0]["fields"] = ["title", "api_token"]
    assert ("api_platform.entities[0].fields[1]", "public_field_secret") in _codes(data)


def test_a_regulated_field_is_never_public() -> None:
    data = _data()
    data["regulated"] = {
        "enabled": True,
        "key_provider": "file",
        "fields": [{"entity": "Product", "field": "title", "mode": "encrypt", "searchable": False}],
    }
    assert ("api_platform.entities[0].fields[0]", "public_field_protected") in _codes(data)


def test_apps_are_validated() -> None:
    data = _data()
    data["api_platform"]["apps"][0]["name"] = "Bad Name"
    assert ("api_platform.apps[0].name", "invalid_app_name") in _codes(data)
    data = _data()
    data["api_platform"]["apps"][1]["name"] = "storefront"
    assert ("api_platform.apps[1].name", "duplicate_app") in _codes(data)
    data = _data()
    data["api_platform"]["apps"][0]["scopes"] = []
    assert ("api_platform.apps[0].scopes", "app_needs_scopes") in _codes(data)
    data = _data()
    data["api_platform"]["apps"][0]["scopes"] = ["Ghost"]
    assert ("api_platform.apps[0].scopes[0]", "app_scope_not_public") in _codes(data)
    data = _data()
    data["api_platform"]["apps"][0]["events"] = ["Not A Slug"]
    assert ("api_platform.apps[0].events[0]", "invalid_event_type") in _codes(data)


def test_too_many_apps() -> None:
    data = _data()
    data["api_platform"]["apps"] = [{"name": f"app-{i}", "scopes": ["Product"]} for i in range(33)]
    assert ("api_platform", "too_many") in _codes(data)


def test_generate_emits_the_block() -> None:
    tree = generate(Spec.model_validate(_data()))
    for path in FILES:
        assert path in tree, path
    settings = tree["app/platform_api/settings.py"]
    assert "'sandbox_rate_limit'" not in settings and "SANDBOX_RATE_LIMIT: str = '5/minute'" in settings
    assert "'internal_cost'" not in settings  # a field that is not listed never reaches the public settings
    assert "app.platform_api.public" in tree["app/main.py"] and "_platform_api_models" in tree["app/models/__init__.py"]
    assert "api_keys" in tree["tests/conftest.py"]


def test_projects_without_the_block_emit_nothing() -> None:
    for name in ("regulated_clinic", "shop_auth", "minimal"):
        tree = generate(Spec.model_validate(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))))
        assert not [p for p in tree if "platform_api" in p or "0045" in p], name
        assert "platform_api" not in tree["app/main.py"]
    data = _data()
    data["api_platform"]["enabled"] = False
    assert not [p for p in generate(Spec.model_validate(data)) if "platform_api" in p]


def test_an_entity_with_owner_or_policy_rules_cannot_be_public() -> None:
    data = _data()
    data["auth"]["permissions"].append({"entity": "Review", "operation": "list", "roles": ["admin"], "row_rule": "owner"})
    review = next(i for i, e in enumerate(data["api_platform"]["entities"]) if e["entity"] == "Review")
    assert (f"api_platform.entities[{review}].entity", "public_entity_row_rule") in _codes(data)
    data = _data()
    data["authorization"] = {"model": "abac", "field_access": [], "policies": [], "attachments": {}}
    assert ("api_platform.entities[0].entity", "public_entity_policy") in _codes(data)


def test_a_field_with_a_read_role_rule_cannot_be_public() -> None:
    data = _data()
    name = data["api_platform"]["entities"][0]["fields"][0]
    entity = data["api_platform"]["entities"][0]["entity"]
    data["authorization"] = {
        "model": "rbac", "policies": [], "attachments": {},
        "field_access": [{"entity": entity, "field": name, "read_roles": ["admin"], "write_roles": None}],
    }
    assert ("api_platform.entities[0].fields[0]", "public_field_restricted") in _codes(data)


def test_a_multi_tenant_project_needs_every_public_entity_tenant_scoped() -> None:
    data = _data()
    assert data["auth"]["multi_tenant"]
    entity = data["api_platform"]["entities"][0]["entity"]
    data["auth"]["permissions"] = [
        p for p in data["auth"]["permissions"] if not (p["entity"] == entity and p.get("row_rule") == "tenant")
    ]
    assert ("api_platform.entities[0].entity", "public_entity_not_tenant_scoped") in _codes(data)
