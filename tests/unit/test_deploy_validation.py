"""Deployment settings: sizing, validation, and what the generator refuses to bundle."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.core import deploy_sizing as sizing
from app.core.generator import generate
from app.core.observability import recommended_sample_ratio
from app.core.spec_models import Spec
from app.core.validation import validate

FIXTURES = Path(__file__).parent.parent / "fixtures" / "specs"


def load(name: str = "deploy_aws") -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data


def issues(raw: dict[str, Any]) -> list[tuple[str, str]]:
    return [(i.path, i.code) for i in validate(Spec.model_validate(raw)) if "deploy" in i.path]


def with_block(**changes: Any) -> dict[str, Any]:
    raw = load()
    raw["deployment"].update(changes)
    return raw


# -- sizing -----------------------------------------------------------------------------------


@pytest.mark.parametrize("cloud", sizing.CLOUDS)
@pytest.mark.parametrize("profile", sizing.PROFILES)
def test_every_profile_resolves_to_a_size_the_cloud_offers(cloud: str, profile: str) -> None:
    r = sizing.resolve(cloud, "dev", profile)
    assert sizing.valid_combo(cloud, r.cpu, r.memory)
    assert 0 <= r.min_instances <= r.max_instances


def test_overrides_win_and_prod_is_protected_by_default() -> None:
    r = sizing.resolve("aws", "prod", "medium", min_instances=4, db_storage_gb=200)
    assert (r.min_instances, r.db_storage_gb) == (4, 200)
    assert r.deletion_protection is True and r.db_high_availability is True
    dev = sizing.resolve("aws", "dev", "small")
    assert dev.deletion_protection is False and dev.db_high_availability is False
    assert sizing.resolve("aws", "dev", "small", deletion_protection=True).deletion_protection


def test_tfvars_are_plain_numbers_and_never_carry_a_secret() -> None:
    text = sizing.tfvars_text("eu-west-1", sizing.resolve("aws", "dev", "small"))
    assert 'environment          = "dev"' in text
    assert "cpu                  = 512" in text
    for word in ("password", "secret", "token", "key"):
        assert word not in text.lower()


def test_sample_ratio_advice_is_monotonic() -> None:
    ratios = [recommended_sample_ratio(n) for n in (None, 1, 50, 100, 500, 5000, 10**6)]
    assert ratios == sorted(ratios, reverse=True)
    assert ratios[0] == 1.0 and ratios[-1] == 0.01


# -- validation -------------------------------------------------------------------------------


@pytest.mark.parametrize("cloud", sizing.CLOUDS)
def test_the_fixtures_are_valid(cloud: str) -> None:
    assert issues(load(f"deploy_{cloud}")) == []


def test_a_project_without_a_deployment_block_is_untouched() -> None:
    raw = load()
    del raw["deployment"]
    assert issues(raw) == []
    assert not any(
        p.startswith(("deploy/", ".github/")) for p in generate(Spec.model_validate(raw))
    )


@pytest.mark.parametrize(
    ("changes", "path"),
    [
        ({"cloud": "oracle"}, "deployment.cloud"),
        ({"region": "Moon Base"}, "deployment.region"),
        ({"region": "westeurope"}, "deployment.region"),  # an Azure name on AWS
        ({"github_repo": "not a repo"}, "deployment.github_repo"),
        ({"github_repo": ""}, "deployment.github_repo"),
        ({"environments": []}, "deployment.environments"),
        ({"environments": [{"name": "Dev!"}]}, "deployment.environments[0].name"),
        ({"environments": [{"name": "dev"}, {"name": "dev"}]}, "deployment.environments[1].name"),
        (
            {"environments": [{"name": "dev", "profile": "huge"}]},
            "deployment.environments[0].profile",
        ),
        (
            {"environments": [{"name": "dev", "cpu": 300, "memory": 1024}]},
            "deployment.environments[0].cpu",
        ),
        ({"environments": [{"name": "dev", "cpu": 512}]}, "deployment.environments[0]"),
        (
            {"environments": [{"name": "dev", "min_instances": 5, "max_instances": 2}]},
            "deployment.environments[0].max_instances",
        ),
        (
            {"environments": [{"name": "dev", "db_storage_gb": 1}]},
            "deployment.environments[0].db_storage_gb",
        ),
    ],
)
def test_bad_settings_are_reported_with_a_path(changes: dict[str, Any], path: str) -> None:
    assert path in [p for p, _ in issues(with_block(**changes))]


def test_an_azure_size_is_not_valid_on_aws() -> None:
    raw = with_block(environments=[{"name": "dev", "cpu": 500, "memory": 1024}])
    assert ("deployment.environments[0].cpu", "invalid_value") in issues(raw)
    raw = with_block(cloud="azure", region="westeurope")
    raw["deployment"]["environments"] = [{"name": "dev", "cpu": 500, "memory": 1024}]
    assert issues(raw) == []


def test_features_the_bundles_cannot_run_are_refused_not_silently_dropped() -> None:
    notes = load()
    vault = json.loads((FIXTURES / "vault_auth.json").read_text(encoding="utf-8"))  # redis tokens
    vault["deployment"] = copy.deepcopy(notes["deployment"])
    assert ("deployment.auth.token_store", "deployment.unsupported") in issues(vault)
    payments = json.loads((FIXTURES / "payments_stripe.json").read_text(encoding="utf-8"))
    payments["deployment"] = copy.deepcopy(notes["deployment"])
    assert ("deployment.payments", "deployment.unsupported") in issues(payments)
    storage = json.loads((FIXTURES / "storage_s3.json").read_text(encoding="utf-8"))
    storage["deployment"] = copy.deepcopy(notes["deployment"])
    assert ("deployment.storage", "deployment.unsupported") in issues(storage)
    keycloak = json.loads((FIXTURES / "keycloak_own.json").read_text(encoding="utf-8"))
    keycloak["deployment"] = copy.deepcopy(notes["deployment"])
    assert ("deployment.auth.keycloak", "deployment.unsupported") in issues(keycloak)


def test_a_shared_keycloak_deploys_and_asks_for_its_address() -> None:
    raw = json.loads((FIXTURES / "keycloak_shared.json").read_text(encoding="utf-8"))
    raw["deployment"] = load()["deployment"]
    assert issues(raw) == []
    files = generate(Spec.model_validate(raw))
    assert "KEYCLOAK_PUBLIC_URL" in files["deploy/aws/environments/prod.tfvars"]
    assert "KEYCLOAK_PUBLIC_URL" in files["docs/DEPLOYMENT.md"]


# -- the generated bundle ---------------------------------------------------------------------


@pytest.mark.parametrize("cloud", sizing.CLOUDS)
def test_generation_is_deterministic_and_names_the_trusted_repository(cloud: str) -> None:
    spec = Spec.model_validate(load(f"deploy_{cloud}"))
    first, second = generate(spec), generate(spec)
    assert first == second
    bootstrap = "\n".join(t for p, t in first.items() if "/bootstrap/" in p)
    assert "acme/notes" in bootstrap
    assert first["docs/DEPLOYMENT.md"].count("acme/notes") >= 1


def test_secret_names_follow_the_auth_settings() -> None:
    files = generate(Spec.model_validate(load()))
    secrets = files["deploy/aws/secrets.tf"]
    assert "AUTH_JWT_SECRET" in secrets
    assert "DATABASE_URL" in secrets
    # values are never in a file: only names
    assert "put-secret-value" in secrets and "<NAME>" in secrets


def test_unknown_workflow_tokens_fail_loudly() -> None:
    from app.core.generator.features.deploy.module import fill_tokens

    with pytest.raises(KeyError):
        fill_tokens("@@NOT_A_TOKEN@@", {})
    assert "@@" not in fill_tokens("@@SLUG@@ @@pin:actions/checkout@@", {"SLUG": "x"})
