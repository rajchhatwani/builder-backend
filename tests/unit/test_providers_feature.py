"""Providers (adapter framework + per-tenant credential vault + emulator): the `providers` block is
validated, off by default (other projects are untouched), secrets never reach the spec or the generated
files, and an enabled project gets the framework, the vault API, the migration and its tests."""

import copy
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from app.core.generator import generate
from app.core.spec_models import Spec
from app.core.validation import validate
from app.core.validation_providers import KINDS, PROVIDER_TABLES

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"
CANARY = "CANARY-b94e17d0a3c85f62e1907a4d-must-not-be-written"


def spec_with(change: Any = None, name: str = "providers_notify") -> Spec:
    data: dict[str, Any] = copy.deepcopy(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))
    if change is not None:
        change(data)
    return Spec.model_validate(data)


def codes(spec: Spec) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in validate(spec)}


def test_the_example_is_valid() -> None:
    assert validate(spec_with()) == []


def test_the_block_is_off_by_default_and_other_projects_get_no_provider_files() -> None:
    spec = spec_with(lambda d: d.update(providers=None))
    assert not [p for p in generate(spec) if "providers" in p]
    assert not any("app.providers" in text or "PROVIDER_VAULT" in text for text in generate(spec).values())
    disabled = spec_with(lambda d: d["providers"].update(enabled=False))
    assert not [p for p in generate(disabled) if "providers" in p]
    assert not [p for p in generate(spec_with(name="events_orders")) if "providers" in p]


@pytest.mark.parametrize(
    "key", ["api_key", "apiKey", "secret", "client_secret", "token", "auth_token", "password", "private_key", "webhook_key"]
)
def test_secret_looking_setting_names_are_refused(key: str) -> None:
    spec = spec_with(lambda d: d["providers"]["adapters"][0]["settings"].update({key: "x"}))
    assert ("providers.adapters[0].settings." + key, "secret_in_spec") in codes(spec)


@pytest.mark.parametrize(
    "value",
    ["sk_" "live_abcdefgh12345678", "whsec" "_abcdefgh12345678", "Bearer abcdefghijkl123", "AKIA" "ABCDEFGHIJKLMNOP", "SG." "abcdefghijklmnop12345",
     "eyJhbGciOiJI.eyJzdWIiOiIx.abc", "-----BEGIN PRIVATE KEY-----", "https://user:pass@example.com/hook"],
)
def test_secret_looking_setting_values_are_refused(value: str) -> None:
    spec = spec_with(lambda d: d["providers"]["adapters"][0]["settings"].update({"endpoint": value}))
    assert ("providers.adapters[0].settings.endpoint", "secret_in_spec") in codes(spec)


def test_the_schema_refuses_unknown_keys_so_a_secret_cannot_hide_in_the_block() -> None:
    with pytest.raises(ValueError):
        spec_with(lambda d: d["providers"].update(api_key=CANARY))
    with pytest.raises(ValueError):
        spec_with(lambda d: d["providers"]["adapters"][0].update(password=CANARY))


def test_kinds_names_and_limits_are_checked() -> None:
    def bad(d: dict[str, Any]) -> None:
        d["providers"]["adapters"] = [
            {"kind": "fax", "name": "acme"},
            {"kind": "email", "name": "emulator"},
            {"kind": "email", "name": "Bad Name"},
            {"kind": "sms", "name": "acme_sms"},
            {"kind": "sms", "name": "acme_sms"},
        ]
        d["providers"].update(timeout_seconds=0, max_attempts=0, breaker_failures=0, breaker_reset_seconds=0, admin_role="nobody")

    found = codes(spec_with(bad))
    assert {
        ("providers.adapters[0].kind", "unknown_kind"),
        ("providers.adapters[1].name", "reserved_name"),
        ("providers.adapters[2].name", "invalid_name"),
        ("providers.adapters[4]", "duplicate_adapter"),
        ("providers.timeout_seconds", "invalid_value"),
        ("providers.max_attempts", "invalid_value"),
        ("providers.breaker_failures", "invalid_value"),
        ("providers.breaker_reset_seconds", "invalid_value"),
        ("providers.admin_role", "unknown_role"),
    } <= found


def test_the_vault_needs_auth_and_its_table_name_is_owned() -> None:
    def no_auth(d: dict[str, Any]) -> None:
        d["auth"] = None
    assert ("providers", "needs_auth") in codes(spec_with(no_auth))

    def clash(d: dict[str, Any]) -> None:
        d["entities"][0]["table_name"] = PROVIDER_TABLES[0]
    assert ("entities[0].table_name", "duplicate_name") in codes(spec_with(clash))


def test_an_enabled_project_gets_the_framework_the_vault_and_a_migration() -> None:
    files = generate(spec_with())
    for path in (
        "app/providers/client.py", "app/providers/vault.py", "app/providers/emulator.py", "app/providers/router.py",
        "app/providers/definitions.py", "app/hooks/providers.py", "alembic/versions/0016_providers.py",
        "tests/test_providers.py", "tests/_providers_support.py",
    ):
        assert path in files, path
    assert "PROVIDER_VAULT_KEY" in files["docker-compose.yml"] and "PROVIDER_VAULT_KEY=" in files[".env.example"]
    assert "from app.providers.router import router" in files["app/main.py"]
    assert "provider_credentials" in files["tests/conftest.py"]
    assert "ADAPTERS" in files["app/providers/definitions.py"] and "acme_mail" in files["app/providers/definitions.py"]
    for kind in KINDS:  # every kind has request models
        assert re.search(rf'"{kind}":', files["app/providers/schemas.py"])


def test_generation_is_deterministic() -> None:
    assert generate(spec_with()) == generate(spec_with())


def test_no_secret_value_reaches_any_generated_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """The generator never reads the environment: a canary in every secret variable the project knows
    appears in none of the files of the zip."""
    for name in ("PROVIDER_VAULT_KEY", "PROVIDER_VAULT_KEY_PREVIOUS", "AUTH_JWT_SECRET", "DATABASE_URL"):
        monkeypatch.setenv(name, CANARY)
    files = generate(spec_with())
    leaking = [path for path, text in files.items() if CANARY in text or CANARY in path]
    assert leaking == []
    assert CANARY in os.environ["PROVIDER_VAULT_KEY"]
    # the only key-looking thing the compose file and .env.example carry is the variable NAME
    assert re.search(r"^PROVIDER_VAULT_KEY=$", files[".env.example"], re.M)
    assert "${PROVIDER_VAULT_KEY:?" in files["docker-compose.yml"]


def test_a_secret_cannot_be_smuggled_through_setting_values_into_the_zip() -> None:
    spec = spec_with(lambda d: d["providers"]["adapters"][0]["settings"].update({"from_name": CANARY, "endpoint": "sk_live_" + CANARY[:20].replace("-", "")}))
    issues = validate(spec)
    assert any(i.code == "secret_in_spec" for i in issues)  # a valid spec is the only one that generates
