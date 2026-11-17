"""Audit B1-020: AWS deploy role cannot escalate within its environment; first apply does not wait."""

import json
from pathlib import Path
from typing import Any

from app.core.generator import generate
from app.core.spec_models import Spec

FIXTURES = Path(__file__).parent.parent / "fixtures" / "specs"


def _files() -> dict[str, str]:
    raw: dict[str, Any] = json.loads((FIXTURES / "deploy_aws.json").read_text(encoding="utf-8"))
    return generate(Spec.model_validate(raw))


def test_f0907_env_role_writes_require_the_permissions_boundary() -> None:
    files = _files()
    main = files["deploy/aws/bootstrap/main.tf"]
    assert "iam:PermissionsBoundary" in main
    assert "aws_iam_policy" in main and "boundary" in main
    # PutRolePolicy / CreateRole are no longer in the unconditional action list
    unconditional = main.split('sid = "RolesOfThisEnvironmentOnly"')[1].split("}\n\n")[0]
    assert "iam:PutRolePolicy" not in unconditional
    assert "iam:CreateRole" not in unconditional
    assert "iam:DeleteRolePermissionsBoundary" in main  # explicit deny
    iam = files["deploy/aws/iam.tf"]
    assert iam.count("permissions_boundary") >= 2  # execution + task roles


def test_f0908_first_apply_does_not_wait_for_steady_state() -> None:
    files = _files()
    assert "var.wait_for_steady_state" in files["deploy/aws/ecs.tf"]
    assert 'variable "wait_for_steady_state"' in files["deploy/aws/variables.tf"]
    wf = files[".github/workflows/deploy.yml"]
    step1 = wf.split("Terraform apply (infrastructure, service unchanged)")[1].split("# Step 2")[0]
    assert "wait_for_steady_state=false" in step1
