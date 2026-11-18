"""Audit B1-001: deploy/CI workflow hardening (static checks on the YAML)."""

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).parent.parent.parent
DEPLOY_TEXT = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
DEPLOY: dict[str, Any] = yaml.safe_load(DEPLOY_TEXT)
CI: dict[str, Any] = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
DEPENDABOT: dict[str, Any] = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text(encoding="utf-8"))


def _steps(job: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = DEPLOY["jobs"][job]["steps"]
    return steps


def test_deploy_job_can_read_packages() -> None:
    perms = DEPLOY["jobs"]["deploy"].get("permissions", {})
    assert perms.get("packages") == "read"


def test_web_image_tag_is_environment_specific_and_not_latest() -> None:
    meta = next(s for s in _steps("images") if s.get("id") == "meta")
    assert "environment" in meta["run"] or "ENVIRONMENT" in meta["run"]
    web = next(s for s in _steps("images") if "builder-web" in str(s.get("with", {}).get("tags", "")))
    assert "builder-web:latest" not in web["with"]["tags"]


def test_registry_token_not_on_ssh_command_line_and_login_is_cleaned_up() -> None:
    step = next(s for s in _steps("deploy") if s.get("name", "").startswith("Pull, migrate"))
    run = step["run"]
    assert "echo '$REGISTRY_TOKEN'" not in run
    assert "DOCKER_CONFIG" in run and "rm -rf" in run


def test_sandbox_images_always_built() -> None:
    for s in _steps("images"):
        if "builder-runner" in str(s.get("with", {})) or "builder-preview-app" in str(s.get("with", {})):
            assert "if" not in s


def test_dependabot_uses_uv() -> None:
    eco = [u["package-ecosystem"] for u in DEPENDABOT["updates"]]
    assert "uv" in eco and "pip" not in eco


def test_ci_runs_audit_suite() -> None:
    runs = [s.get("run", "") for s in CI["jobs"]["backend"]["steps"]]
    assert any("tests/audit" in r for r in runs)


def test_required_vars_checked_before_publish_and_deploy() -> None:
    images = _steps("images")
    idx = next(i for i, s in enumerate(images) if "docker/build-push-action" in s.get("uses", ""))
    assert any("BB_DOMAIN" in s.get("run", "") for s in images[:idx])
    deploy = _steps("deploy")
    assert any("DEPLOY_HOST" in s.get("run", "") and "exit 1" in s.get("run", "") for s in deploy[:2])


def test_production_requires_release_branch() -> None:
    assert "merge-base --is-ancestor" in DEPLOY_TEXT
