"""CO-4 (SENTINEL M-3): the access rules a hook's `find_rows` follows are derived from the entity's own list
endpoint, fail closed, and are emitted for every reading hook. The behaviour on a database is proved by
tests/e2e/hooks_access_scenarios.py and hooks_access_abac_scenarios.py."""

import ast
import json
from typing import Any

from app.core.generator import generate
from tests.unit.test_generator import load_spec


def rules_of(name: str) -> dict[str, Any]:
    source = generate(load_spec(name))["app/hooks_gen/access.py"]
    start = source.index("RULES: dict[str, dict[str, Any]] = ") + len("RULES: dict[str, dict[str, Any]] = ")
    end = source.index("\n\n\ndef rule_for")
    return ast.literal_eval(source[start:end])  # type: ignore[no-any-return]


def test_role_rules_follow_the_list_permission() -> None:
    rules = rules_of("hooks_access")
    assert rules["Note"]["mode"] == "roles" and rules["Note"]["op"] == "list"
    assert rules["Note"]["build"] == {
        "roles": ("admin", "member"), "owner": True, "admin_sees_all": True, "tenant": True,
    }
    assert rules["Ledger"]["build"] == {"roles": ("admin",), "tenant": True}
    assert all(r["needs_user"] and r["tenant"] for r in rules.values())


def test_policy_rules_for_abac() -> None:
    rule = rules_of("hooks_access_abac")["Ticket"]
    assert rule["mode"] == "policy" and rule["needs_user"] is True and rule["op"] == "list"


def test_only_entities_declared_in_reads_are_listed() -> None:
    assert set(rules_of("hooks_invoice")) == {"Invoice"}  # notify_approved reads Invoice, nothing else


def test_the_gate_manifest_covers_the_access_module() -> None:
    files = generate(load_spec("hooks_access"))
    manifest = json.loads(files["platform/hooks.json"])
    assert "app/hooks_gen/access.py" in manifest["generated_sha256"]


def test_the_sdk_documents_the_reads_contract_and_the_read_path_uses_the_access_module() -> None:
    files = generate(load_spec("hooks_access"))
    assert "filtered by the access policies of the person" in files["app/platform_sdk/__init__.py"]
    runtime = files["app/hooks_gen/runtime.py"]
    assert "access.repo_kwargs(entity, caller)" in runtime and "list_items" in runtime
    assert "SET TRANSACTION READ ONLY" in runtime
