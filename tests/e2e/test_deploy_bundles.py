"""Generated CI/CD and Terraform, checked with the real tools in Docker (no cloud account needed).

For each cloud: `terraform fmt -check`, `terraform init -backend=false` and `terraform
validate` on the stack and on the one-time bootstrap (the real provider schemas),
`actionlint` on the workflows, and static checks: no secret-looking literal is written,
every action is pinned to a commit, and every value in a tfvars file names a declared
variable. `terraform apply` against a real account is not run here (see MASTER_PLAN.md, L7).
"""

import os
import re
import subprocess
import tempfile
from pathlib import Path

import pytest

from app.core.deploy_pins import TERRAFORM_VERSION
from app.core.generator import generate
from app.core.spec_models import Spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"
CLOUDS = ("aws", "azure", "gcp")

SECRET_SHAPES = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(password|secret|token|api_key)\s*=\s*\"[^\"$]{6,}\""),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)client_secret"),
)
# Provided by the pipeline on the command line, so they are not in the tfvars files.
PIPELINE_VARS = {
    "image",
    "project_id",
    "subscription_id",
    "registry_name",
    "registry_resource_group",
}


def docker(*args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=900, env=env, check=False
    )


@pytest.fixture(scope="module")
def plugin_cache() -> Path:
    cache = Path(tempfile.gettempdir()) / "tf-plugin-cache"
    cache.mkdir(exist_ok=True)
    return cache


def bundle(cloud: str, tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, str]]:
    spec = Spec.model_validate_json((FIXTURES / f"deploy_{cloud}.json").read_text(encoding="utf-8"))
    files = generate(spec)
    root = tmp_path_factory.mktemp(f"deploy_{cloud}")
    for path, content in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return root, files


@pytest.mark.parametrize("cloud", CLOUDS)
def test_terraform_is_formatted_and_valid(
    cloud: str, tmp_path_factory: pytest.TempPathFactory, plugin_cache: Path
) -> None:
    root, _ = bundle(cloud, tmp_path_factory)
    base = [
        "run", "--rm",
        "-v", f"{root}:/w",
        "-v", f"{plugin_cache}:/cache",
        "-e", "TF_PLUGIN_CACHE_DIR=/cache",
        "-w", "/w",
        f"hashicorp/terraform:{TERRAFORM_VERSION}",
    ]  # fmt: skip
    fmt = docker(*base, "fmt", "-check", "-recursive", "-diff", f"deploy/{cloud}")
    assert fmt.returncode == 0, fmt.stdout + fmt.stderr
    for directory in (f"deploy/{cloud}", f"deploy/{cloud}/bootstrap"):
        init = docker(*base, f"-chdir={directory}", "init", "-backend=false", "-input=false")
        assert init.returncode == 0, directory + init.stdout + init.stderr
        valid = docker(*base, f"-chdir={directory}", "validate", "-no-color")
        assert valid.returncode == 0, directory + valid.stdout + valid.stderr


@pytest.mark.parametrize("cloud", CLOUDS)
def test_workflows_pass_actionlint(cloud: str, tmp_path_factory: pytest.TempPathFactory) -> None:
    root, _ = bundle(cloud, tmp_path_factory)
    result = docker(
        "run", "--rm", "-v", f"{root}:/repo", "-w", "/repo", "rhysd/actionlint:latest",
        "-no-color", ".github/workflows/ci.yml", ".github/workflows/deploy.yml",
    )  # fmt: skip
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("cloud", CLOUDS)
def test_no_secret_is_written_and_actions_are_pinned(
    cloud: str, tmp_path_factory: pytest.TempPathFactory
) -> None:
    _, files = bundle(cloud, tmp_path_factory)
    for path, text in files.items():
        if not path.startswith(("deploy/", ".github/")):
            continue
        for shape in SECRET_SHAPES:
            assert not shape.search(text), f"{path} matches {shape.pattern}"
    for path, text in files.items():
        if path.startswith(".github/workflows/"):
            for use in re.findall(r"uses:\s*(\S+)", text):
                assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", use), f"{path}: {use} is not pinned"
    # the trust is limited to one repository and one GitHub environment
    trust = "\n".join(t for p, t in files.items() if "bootstrap" in p)
    assert "acme/notes" in trust
    assert "environment" in trust


@pytest.mark.parametrize("cloud", CLOUDS)
def test_tfvars_only_set_declared_variables_and_nothing_required_is_missing(
    cloud: str, tmp_path_factory: pytest.TempPathFactory
) -> None:
    _, files = bundle(cloud, tmp_path_factory)
    declared = set(re.findall(r'^variable "(\w+)"', files[f"deploy/{cloud}/variables.tf"], re.M))
    required = set(
        re.findall(
            r'^variable "(\w+)" \{(?:(?!^\}).)*?\n\}',
            files[f"deploy/{cloud}/variables.tf"],
            re.M | re.S,
        )
    )
    with_default = {
        name
        for name, body in re.findall(
            r'^variable "(\w+)" \{(.*?)^\}', files[f"deploy/{cloud}/variables.tf"], re.M | re.S
        )
        if re.search(r"^\s*default\s*=", body, re.M)
    }
    needed = (required - with_default) - PIPELINE_VARS
    for path, text in files.items():
        if path.startswith(f"deploy/{cloud}/environments/"):
            assigned = set(re.findall(r"^(\w+)\s*=", text, re.M))
            assert assigned <= declared, f"{path} sets undeclared {assigned - declared}"
            assert needed <= assigned, f"{path} misses {needed - assigned}"
