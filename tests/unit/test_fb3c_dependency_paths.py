"""A-003 (B3-9): every way of declaring a package goes through the dependency policy.

The platform installs nothing at run time (the preview image is prebuilt), so the install paths are the
files an agent or a user can put into a draft workspace. These tests drive the real gate, the agent's
write-path check and the manifest classifier with hostile names."""

import uuid
from pathlib import Path
from typing import Any, cast

import pytest

from app.core.generator import generate
from app.core.spec_models import Spec
from app.services.agent import gates
from app.services.agent.contract import Actor, Phase, Plan, ToolContext
from app.services.agent.tools._common import ToolRefusal, custom_write_path
from app.services.dependency_policy_service import is_dependency_manifest

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"

MANIFESTS = [
    "pyproject.toml", "app/custom/pyproject.toml", "app/custom/package.json", "app/custom/setup.py",
    "app/custom/setup.cfg", "app/custom/Pipfile", "app/custom/poetry.lock", "app/custom/constraints.txt",
    "app/custom/dev-requirements.txt", "app/custom/requirements.in", "app/custom/requirements/base.txt",
    "tests/custom/requirements-extra.txt", "app/custom/environment.yml", "app/custom/yarn.lock",
]
NOT_MANIFESTS = ["app/custom/notes.py", "app/hooks/match_invoice.py", "tests/custom/test_x.py", "README.md",
                 "app/custom/requirements_notes.py", "app/custom/data.txt"]  # fmt: skip


@pytest.mark.parametrize("rel", MANIFESTS)
def test_every_dependency_manifest_is_recognised(rel: str) -> None:
    assert is_dependency_manifest(rel)


@pytest.mark.parametrize("rel", NOT_MANIFESTS)
def test_ordinary_files_are_not_manifests(rel: str) -> None:
    assert not is_dependency_manifest(rel)


def _project(tmp_path: Path) -> tuple[Path, Spec]:
    spec = Spec.model_validate_json((FIXTURES / "shop_auth.json").read_text(encoding="utf-8"))
    root = tmp_path / "wt"
    for rel, content in generate(spec).items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root, spec


@pytest.mark.parametrize("rel", [m for m in MANIFESTS if m != "pyproject.toml"])
def test_the_gate_refuses_a_hand_written_manifest_outside_the_generated_zone(tmp_path: Path, rel: str) -> None:
    root, spec = _project(tmp_path)
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"dependencies": {"left-pad": "1.0.0"}}\n', encoding="utf-8")
    report = gates.run_gates(root, spec)
    hits = [f for f in report.failures if f.rule_id == "g8.dependency" and f.location == rel]
    assert hits, [(f.rule_id, f.location) for f in report.failures]


def test_the_generated_manifests_still_pass(tmp_path: Path) -> None:
    root, spec = _project(tmp_path)
    assert gates.run_gates(root, spec).ok


def _ctx(root: Path) -> ToolContext:
    return ToolContext(
        session=cast(Any, None), settings=cast(Any, None), org_id=uuid.uuid4(), project_id=uuid.uuid4(),
        run_id=uuid.uuid4(), actor=Actor("agent", uuid.uuid4()), phase=Phase.build,
        plan=Plan(uuid.uuid4(), entities=frozenset(), hooks=frozenset(), zones=frozenset(), dependencies=frozenset()),
        worktree=str(root),
    )  # fmt: skip


@pytest.mark.parametrize(
    "rel",
    ["app/custom/Pipfile", "app/custom/constraints.txt", "app/custom/dev-requirements.txt",
     "app/custom/requirements.in", "tests/custom/requirements-extra.txt", "app/custom/requirements/base.txt",
     "app/custom/setup.py"],
)  # fmt: skip
def test_the_agent_cannot_write_a_manifest_in_any_spelling(tmp_path: Path, rel: str) -> None:
    root, _ = _project(tmp_path)
    with pytest.raises(ToolRefusal):
        custom_write_path(_ctx(root), rel, "add_test")


def test_the_agent_can_still_write_custom_code(tmp_path: Path) -> None:
    root, _ = _project(tmp_path)
    target, norm = custom_write_path(_ctx(root), "app/custom/notes.py", "add_test")
    assert norm == "app/custom/notes.py" and target.parent.name == "custom"
