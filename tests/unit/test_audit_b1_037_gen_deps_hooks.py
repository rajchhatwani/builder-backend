"""Audit B1-037: generated-project dependency list, hook reads vs field rules, outbox purge, SDK row limit."""

import json
from pathlib import Path
from typing import Any

from app.core.generator import generate
from app.core.spec_models import Spec

FIXTURES = Path(__file__).parent.parent / "fixtures" / "specs"


def _files(name: str, patch: Any = None) -> dict[str, str]:
    raw: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    if patch:
        patch(raw)
    return generate(Spec.model_validate(raw))


def test_f1170_providers_vault_projects_list_cryptography() -> None:
    files = _files("providers_notify.json")
    assert "app/providers/vault.py" in files
    assert "cryptography" in files["requirements.txt"]


def _guard_note(raw: dict[str, Any]) -> None:
    raw["authorization"] = {
        "model": "rbac",
        "field_access": [{"entity": "Note", "field": "title", "read_roles": ["admin"]}],
    }


def test_f1171_hook_reads_apply_field_level_read_rules() -> None:
    files = _files("hooks_access.json", _guard_note)
    access = files["app/hooks_gen/access.py"]
    assert "def hidden_fields" in access and "field_access.hidden_read" in access
    assert "'guarded': True" in access
    runtime = files["app/hooks_gen/runtime.py"]
    assert "access.hidden_fields(entity, caller)" in runtime


def test_f1171_unguarded_project_has_no_field_access_import() -> None:
    access = _files("hooks_access.json")["app/hooks_gen/access.py"]
    assert "field_access" not in access


def test_f1175_purge_is_not_starved_by_busy_outbox() -> None:
    files = _files("events_orders.json")
    relay = next((v for k, v in files.items() if k == "app/events/relay.py"), "")
    assert relay, "events fixture missing"
    body = relay.split("async def run_forever", 1)[1]
    assert body.index("PURGE_EVERY_SECONDS") < body.index("deliver_batch")


def test_f1176_find_rows_default_limit_fits_small_budget() -> None:
    env = _files("hooks_access.json")["app/platform_sdk/env.py"]
    assert "limit: int | None = None" in env


def test_f1172_generated_documents_test_follows_template_compute() -> None:
    src = _files("docs_desk.json")["tests/test_documents.py"]
    assert 'key = template["compute"]' in src
    assert '"items": [{"description"' not in src
    assert '{"items": "not a list"}' not in src


def test_f1173_entity_bound_template_cannot_declare_compute() -> None:
    from app.core.validation import validate

    def patch(raw: dict[str, Any]) -> None:
        for t in raw["documents"]["templates"]:
            if t.get("entity"):
                t["compute"] = "items"

    raw = json.loads((FIXTURES / "docs_desk.json").read_text(encoding="utf-8"))
    patch(raw)
    codes = [i.code for i in validate(Spec.model_validate(raw))]
    assert "documents.compute_needs_unbound" in codes


def test_f1174_events_projects_document_the_relay() -> None:
    files = _files("events_orders.json")
    assert "EVENTS_RELAY_ENABLED" in files["README.md"] and "requeue_failed" in files["README.md"]
    assert "EVENTS_MAX_ATTEMPTS" in files[".env.example"]
    plain = _files("hooks_access.json")
    assert "EVENTS_RELAY_ENABLED" not in plain["README.md"] + plain[".env.example"]
