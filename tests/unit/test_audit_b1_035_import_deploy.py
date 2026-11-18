"""Audit B1-035: import dedupe is no existence oracle for create-only callers; deploy pipeline / validation fixes."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.core import deploy_sizing as sizing
from app.core.generator import generate
from app.core.generator.features.data_import.module import caller_may_list
from app.core.spec_models import Spec
from app.core.validation import validate

from tests.unit.test_deploy_validation import issues, load, with_block
from tests.unit.test_generator_data_import import _spec_files

FIXTURES = Path(__file__).parent.parent / "fixtures" / "specs"


def _gen(cloud: str) -> dict[str, str]:
    raw: dict[str, Any] = json.loads(
        (FIXTURES / f"deploy_{cloud}.json").read_text(encoding="utf-8")
    )
    return generate(Spec.model_validate(raw))


def _acc(op: str, **kw: Any) -> SimpleNamespace:
    base = {
        "roles": (),
        "owner": False,
        "tenant": False,
        "admin_sees_all": False,
        "match": None,
        "policy": False,
    }
    base.update(kw)
    ns = SimpleNamespace(op=op, **base)
    ns.needs_user = bool(ns.roles or ns.owner or ns.tenant or kw.get("authenticate"))
    return ns


def _ent(ops: tuple[str, ...], *access: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(ops=ops, access=access)


def test_f1072_create_only_callers_get_no_duplicate_answer() -> None:
    assert not caller_may_list(_ent(("create",), _acc("create", roles=("writer",))))
    assert not caller_may_list(
        _ent(("create", "list"), _acc("list", roles=("admin",)))
    )  # public create
    assert not caller_may_list(
        _ent(("create", "list"), _acc("create", roles=("writer",)), _acc("list", roles=("admin",)))
    )
    assert caller_may_list(
        _ent(
            ("create", "list"),
            _acc("create", roles=("admin",)),
            _acc("list", roles=("admin", "writer")),
        )
    )
    assert caller_may_list(_ent(("create", "list")))  # everything public
    assert not caller_may_list(
        _ent(
            ("create", "list"), _acc("create", roles=("a",)), _acc("list", roles=("a",), owner=True)
        )
    )


def test_f1072_service_rejects_existing_rows_generically_when_caller_may_not_list() -> None:
    files = _spec_files()
    svc = files["app/imports/service.py"]
    assert "may_list: bool = False" in svc
    assert "key in existing and not may_list" in svc
    assert "may_list=" in files["app/imports/router.py"]


def test_f1073_push_deploys_run_the_ci_checks_first() -> None:
    for cloud in ("aws", "azure", "gcp"):
        files = _gen(cloud)
        wf = files[".github/workflows/deploy.yml"]
        assert "uses: ./.github/workflows/ci.yml" in wf and "needs: checks" in wf, cloud
        assert "workflow_call:" in files[".github/workflows/ci.yml"], cloud


def test_f1074_azure_secrets_are_checked_before_the_service_exists() -> None:
    wf = _gen("azure")[".github/workflows/deploy.yml"]
    check = wf.index("Check that every secret has been set")
    assert wf.index("-target=azurerm_key_vault_secret.app") < check
    assert check < wf.index("Terraform apply (infrastructure, service unchanged)")


def test_f1075_production_names_are_protected_and_not_dev_like() -> None:
    assert sizing.resolve("aws", "production", "small").deletion_protection is True
    assert sizing.resolve("aws", "live", "small").deletion_protection is True
    assert sizing.resolve("aws", "dev", "small").deletion_protection is False
    raw = load("deploy_aws")
    raw["deployment"]["environments"] = [{"name": "production", "profile": "small"}]
    tf = next(
        v for k, v in generate(Spec.model_validate(raw)).items() if k.endswith("production.tfvars")
    )
    assert "development" not in tf and "allow_http = true" not in tf


def test_f1076_azure_slug_is_limited_for_the_container_apps_environment() -> None:
    raw = with_block(cloud="azure", region="westeurope")

    def slug_issues(n: int) -> list[tuple[str, str]]:
        raw["project"]["slug"] = "a" * n
        return [(i.path, i.code) for i in validate(Spec.model_validate(raw))]

    assert ("project.slug", "invalid_value") in slug_issues(30)
    assert ("project.slug", "invalid_value") not in slug_issues(10)


def test_f1077_aws_needs_at_least_one_instance() -> None:
    path = ("deployment.environments[0].min_instances", "invalid_value")
    raw = with_block(cloud="aws", region="eu-west-1")
    raw["deployment"]["environments"] = [{"name": "dev", "min_instances": 0}]
    assert path in issues(raw)
    raw = with_block(cloud="azure", region="westeurope")
    raw["deployment"]["environments"] = [{"name": "dev", "min_instances": 0}]
    assert path not in issues(raw)


def test_f1078_state_access_is_scoped_to_the_environment_prefix() -> None:
    main = _gen("aws")["deploy/aws/bootstrap/main.tf"]
    state = main.split('sid       = "TerraformState"')[1].split('sid       = "TerraformStateList"')[
        0
    ]
    assert "/${var.project}/${each.value}/*" in state
    assert '"${aws_s3_bucket.state.arn}/*"' not in main.split('sid       = "PushImages"')[1]
    assert "s3:prefix" in main
