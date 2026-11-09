"""Suite identity, path (a): validation and generator output for a new project inside a suite."""

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from app.core.generator import generate
from app.core.spec_models import Spec
from app.core.validation import ValidationIssue, validate

TESTS = Path(__file__).resolve().parent.parent
FIXTURES = TESTS / "fixtures" / "specs"
GOLDEN = TESTS / "golden" / "keycloak_suite"


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data


def issues(data: dict[str, Any]) -> list[ValidationIssue]:
    return validate(Spec.model_validate(data))


def codes(data: dict[str, Any]) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in issues(data)}


@pytest.fixture(scope="module")
def suite_files() -> dict[str, str]:
    return generate(Spec.model_validate(load("keycloak_suite")))


def test_the_suite_fixture_is_valid() -> None:
    assert issues(load("keycloak_suite")) == []


# --- validation -------------------------------------------------------------------------


def test_a_suite_needs_keycloak() -> None:
    data = load("keycloak_suite")
    data["auth"]["provider"] = "builtin"
    assert ("auth.suite", "suite_requires_keycloak") in codes(data)


def test_the_realm_is_derived_not_free_text() -> None:
    data = load("keycloak_suite")
    data["auth"]["keycloak"]["realm"] = "acme"
    assert ("auth.keycloak.realm", "suite_realm_derived") in codes(data)


def test_a_suite_member_uses_shared_mode() -> None:
    data = load("keycloak_suite")
    data["auth"]["keycloak"]["mode"] = "own"
    assert ("auth.keycloak.mode", "suite_requires_shared") in codes(data)


@pytest.mark.parametrize(
    ("issuer", "code"),
    [
        ("http://id.acme.com/realms/suite-acme", "invalid_hub_issuer"),
        ("https://id.acme.com", "hub_issuer_realm_mismatch"),
        ("https://id.acme.com/realms/acme", "hub_issuer_realm_mismatch"),
        ("https://id.acme.com/realms/suite-other", "hub_issuer_realm_mismatch"),
        ("https://id.acme.com/realms/suite-acme?x=1", "invalid_hub_issuer"),
        ("https://user:pw@id.acme.com/realms/suite-acme", "invalid_hub_issuer"),
        ("ftp://id.acme.com/realms/suite-acme", "invalid_hub_issuer"),
    ],
)
def test_hub_issuer_rules(issuer: str, code: str) -> None:
    data = load("keycloak_suite")
    data["auth"]["suite"]["hub_issuer"] = issuer
    assert ("auth.suite.hub_issuer", code) in codes(data)


def test_http_hub_issuer_is_fine_on_localhost() -> None:
    data = load("keycloak_suite")
    data["auth"]["suite"]["hub_issuer"] = "http://localhost:8081/realms/suite-acme"
    assert issues(data) == []


def test_hub_issuer_is_optional() -> None:
    data = load("keycloak_suite")
    data["auth"]["suite"]["hub_issuer"] = None
    assert issues(data) == []


@pytest.mark.parametrize("state", ["none", "planned", "joined"])
def test_join_states_allowed(state: str) -> None:
    data = load("keycloak_suite")
    data["auth"]["suite"]["join_state"] = state
    assert issues(data) == []


def test_unknown_join_state_is_refused() -> None:
    data = load("keycloak_suite")
    data["auth"]["suite"]["join_state"] = "migrating"
    assert ("auth.suite.join_state", "invalid_value") in codes(data)


def test_a_suite_id_that_would_overflow_the_realm_name_is_refused() -> None:
    data = load("keycloak_suite")
    long_id = "a" * 58
    data["auth"]["suite"]["suite_id"] = long_id
    data["auth"]["keycloak"]["realm"] = "suite-" + long_id
    found = codes(data)
    assert ("auth.suite.suite_id", "suite_id_too_long") in found


# --- generator --------------------------------------------------------------------------


def test_the_realm_config_uses_the_shared_realm_and_one_client(suite_files: dict[str, str]) -> None:
    doc = json.loads(suite_files["keycloak/clients.json"])
    assert doc["realm"] == "suite-acme"
    assert [c["clientId"] for c in doc["clients"]] == ["suite-portal"]
    assert "keycloak/realm.json" not in suite_files  # the hub is not started by the project
    client = doc["clients"][0]
    assert client["publicClient"] is True
    assert client["directAccessGrantsEnabled"] is False
    mapper = next(m for m in client["protocolMappers"] if m["name"] == "api-audience")
    assert mapper["config"]["included.client.audience"] == "suite-portal"
    assert "suite-audience" in client["defaultClientScopes"]
    assert doc["suite"]["audience"] == "suite-portal"
    assert doc["suite"]["realm_base"]["realm"] == "suite-acme"
    # Roles are client roles of the project's own client.
    assert {r["name"] for r in doc["roles"]} == {"admin", "agent"}
    assert all(r["clientRole"] for r in doc["roles"])


def test_the_api_accepts_only_the_suite_issuer_and_its_own_audience(
    suite_files: dict[str, str],
) -> None:
    config = suite_files["app/auth/config.py"]
    assert "REALM = 'suite-acme'" in config
    assert "API_CLIENT_ID = 'suite-portal'" in config
    assert "SUITE_ID = 'acme'" in config
    assert "HUB_ISSUER: str | None = 'https://id.acme.com/realms/suite-acme'" in config
    assert 'config.API_CLIENT_ID not in audiences' in suite_files["app/auth/oidc.py"]


def test_env_and_readme_expose_the_issuer(suite_files: dict[str, str]) -> None:
    env = suite_files[".env.example"]
    assert "KEYCLOAK_PUBLIC_URL=https://id.acme.com\n" in env
    assert "/realms/suite-acme" in env
    assert "sign-in suite `acme`" in suite_files["README.md"]


def test_no_secret_is_rendered(suite_files: dict[str, str]) -> None:
    assert "secret" not in suite_files["keycloak/clients.json"].lower()


def test_the_suite_register_script_creates_the_realm_and_audience(
    suite_files: dict[str, str],
) -> None:
    script = suite_files["scripts/keycloak_register.py"]
    assert "def ensure_realm" in script
    assert "def ensure_audience_scope" in script
    compile(script, "keycloak_register.py", "exec")


def test_a_project_outside_a_suite_is_unchanged() -> None:
    plain = load("keycloak_shared")
    files = generate(Spec.model_validate(plain))
    assert "suite" not in json.loads(files["keycloak/clients.json"])
    assert "ensure_realm" not in files["scripts/keycloak_register.py"]
    assert "SUITE_ID" not in files["app/auth/config.py"]
    # Same spec with the suite switched off in a copy gives identical bytes.
    other = deepcopy(plain)
    other["auth"]["suite"] = None
    assert generate(Spec.model_validate(other)) == files


def test_the_suite_realm_config_matches_the_golden_file(suite_files: dict[str, str]) -> None:
    target = GOLDEN / "keycloak" / "clients.json"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(suite_files["keycloak/clients.json"], encoding="utf-8", newline="\n")
    assert suite_files["keycloak/clients.json"] == target.read_text(encoding="utf-8")


def test_generation_is_deterministic() -> None:
    spec = Spec.model_validate(load("keycloak_suite"))
    assert generate(spec) == generate(spec)
