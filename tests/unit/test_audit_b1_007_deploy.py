"""Audit B1-007: compose APP_ENV once, deploy IAM/names/ignore files, unsupported deploy features."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.core.generator import generate
from app.core.spec_models import Spec
from app.core.validation import validate

FIXTURES = Path(__file__).parent.parent / "fixtures" / "specs"


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data


def deploy_issues(raw: dict[str, Any]) -> list[tuple[str, str]]:
    return [(i.path, i.code) for i in validate(Spec.model_validate(raw)) if "deploy" in i.path]


class _DupLoader(yaml.SafeLoader):
    pass


def _no_dups(loader: _DupLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        assert key not in seen, f"DUP {key}"
        seen.add(key)
    return _orig(loader, node, deep)


_orig = _DupLoader.construct_mapping
_DupLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, lambda l, n: _no_dups(l, n, True))  # type: ignore[arg-type]


def test_compose_has_no_duplicate_keys_for_keycloak_with_providers() -> None:
    raw = load("keycloak_own")
    raw["providers"] = load("providers_notify")["providers"]
    text = generate(Spec.model_validate(raw))["docker-compose.yml"]
    yaml.load(text, Loader=_DupLoader)  # noqa: S506


def test_compose_has_no_duplicate_keys_for_keycloak_with_storage() -> None:
    raw = load("keycloak_own")
    storage = load("storage_s3")
    raw["storage"] = storage["storage"]
    for rule in raw["storage"]["roles"].values():
        rule[:] = ["admin"]
    text = generate(Spec.model_validate(raw))["docker-compose.yml"]
    yaml.load(text, Loader=_DupLoader)  # noqa: S506


def test_aws_deploy_roles_are_outside_the_managed_role_pattern() -> None:
    files = generate(Spec.model_validate(load("deploy_aws")))
    main = files["deploy/aws/bootstrap/main.tf"]
    assert '"${var.project}-deploy-${each.value}"' not in main
    assert "role/${var.project}-*" not in main
    assert "iam:PolicyARN" in main or "PermissionsBoundary" in main


@pytest.mark.parametrize("cloud", ["aws", "gcp"])
def test_rerun_skips_the_build_when_the_tag_is_already_pushed(cloud: str) -> None:
    wf = generate(Spec.model_validate(load(f"deploy_{cloud}")))[".github/workflows/deploy.yml"]
    assert "id: exists" in wf
    assert "steps.exists.outputs.found" in wf


def test_aws_pipeline_fails_on_a_rolled_back_deployment() -> None:
    files = generate(Spec.model_validate(load("deploy_aws")))
    assert "wait_for_steady_state" in files["deploy/aws/ecs.tf"]
    assert "FAILED" in files[".github/workflows/deploy.yml"]


def test_providers_jobs_workflows_are_refused_for_deployment() -> None:
    base = load("deploy_aws")
    prov = load("providers_notify")
    prov["deployment"] = copy.deepcopy(base["deployment"])
    assert ("deployment.providers", "deployment.unsupported") in deploy_issues(prov)
    jobs = load("jobs_invoices")
    jobs["deployment"] = copy.deepcopy(base["deployment"])
    assert ("deployment.jobs", "deployment.unsupported") in deploy_issues(jobs)


def test_sns_is_allowed_on_the_task_role_and_credentialed_elsewhere() -> None:
    aws = generate(Spec.model_validate(load("deploy_aws")))
    assert "sns:Publish" in aws["deploy/aws/iam.tf"]
    gcp = generate(Spec.model_validate(load("deploy_gcp")))
    assert "AWS_ACCESS_KEY_ID" in gcp["deploy/gcp/secrets.tf"]
    az = generate(Spec.model_validate(load("deploy_azure")))
    assert "AWS_SECRET_ACCESS_KEY" in az["deploy/azure/secrets.tf"]


@pytest.mark.parametrize("cloud", ["aws", "gcp"])
def test_long_slug_is_refused_for_deployment(cloud: str) -> None:
    raw = load(f"deploy_{cloud}")
    raw["project"]["slug"] = "a" * 40
    found = [(i.path, i.code) for i in validate(Spec.model_validate(raw))]
    assert ("project.slug", "invalid_value") in found


def test_azure_key_vault_name_is_unique_per_environment() -> None:
    files = generate(Spec.model_validate(load("deploy_azure")))
    assert "substr(local.short, 0, 15)" not in files["deploy/azure/secrets.tf"]
    assert "md5(" in files["deploy/azure/secrets.tf"] or "sha" in files["deploy/azure/secrets.tf"]


def test_ignore_files_exclude_terraform_state() -> None:
    files = generate(Spec.model_validate(load("deploy_aws")))
    assert "*.tfstate" in files[".gitignore"]
    assert ".terraform/" in files[".gitignore"]
    assert "deploy/" in files[".dockerignore"]
