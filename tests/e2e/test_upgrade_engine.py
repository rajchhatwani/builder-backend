"""CP-6E: the upgrade patch applied for real. Builds the patch for a real generated tree against an altered
BASE, then merges it into an owner's git repo with `git apply --3way`. Needs only a `git` binary."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.core import upgrade_engine as ue
from app.core.generator.engine import generate
from app.core.generator.zones import zone_for
from app.core.spec_models import Spec

SPECS = Path(__file__).resolve().parents[1] / "fixtures" / "specs"
pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs a git binary")

GENERATED_FILE = "app/main.py"
SEEDED_FILE = "README.md"
EXTRA_BASE_FILE = "app/obsolete_module.py"  # in the base only: the upgrade removes it
NEW_FILE = "app/brand_new_module.py"  # in the new tree only: the upgrade adds it


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    out = subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True)
    if check:
        assert out.returncode == 0, out.stderr + out.stdout
    return out


def _write(repo: Path, tree: dict[str, str]) -> None:
    for path, content in tree.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")


@pytest.fixture(scope="module")
def trees() -> tuple[dict[str, str], dict[str, str]]:
    spec = Spec.model_validate(json.loads((SPECS / "hooks_invoice.json").read_text()))
    full = generate(spec)
    return full, ue.non_custom(full)


def _base(real: dict[str, str]) -> dict[str, str]:
    base = dict(real)
    base[GENERATED_FILE] = "# old generator header\n" + base[GENERATED_FILE]
    lines = base[SEEDED_FILE].split("\n")
    lines[0] = "# OLD seeded title"
    base[SEEDED_FILE] = "\n".join(lines)
    base[EXTRA_BASE_FILE] = "OLD = True\n"
    base.pop(NEW_FILE, None)
    return base


def test_patch_merges_with_git_apply_3way(trees: tuple[dict[str, str], dict[str, str]], tmp_path: Path) -> None:
    full, real = trees
    custom = {p: c for p, c in full.items() if zone_for(p) == "custom"}
    assert custom and len(real[SEEDED_FILE].split("\n")) > 12, "fixture needs a long README and custom files"
    real = {**real, NEW_FILE: "NEW = True\n"}
    base = _base({k: v for k, v in real.items() if k != NEW_FILE})

    plan = ue.plan_upgrade(base, {**real, **custom})  # the full new tree: custom paths are only listed
    changed = {f["path"]: f for f in plan.files}
    assert set(changed) == {GENERATED_FILE, SEEDED_FILE, EXTRA_BASE_FILE, NEW_FILE}
    assert changed[GENERATED_FILE]["zone"] == "generated" and changed[SEEDED_FILE]["zone"] == "seeded"
    assert changed[EXTRA_BASE_FILE]["change"] == "removed" and changed[NEW_FILE]["change"] == "added"
    assert plan.kept == sorted(custom)
    assert not any(c in plan.patch_text for c in custom), "no custom path in the patch"

    repo = tmp_path / "owner"
    repo.mkdir()
    _git(repo, "init", "-q")
    _write(repo, {**base, **custom})
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base export")

    # the owner works: a different region of the seeded file, and a custom-zone file
    seeded = (repo / SEEDED_FILE).read_text()
    (repo / SEEDED_FILE).write_text(seeded.rstrip("\n") + "\n\nOwner notes: deploy runs on Fridays.\n", newline="")
    custom_path = sorted(custom)[0]
    owner_custom = "# my own code, hands off\n" + custom[custom_path]
    (repo / custom_path).write_text(owner_custom, newline="")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "owner edits")

    (tmp_path / "upgrade.patch").write_text(plan.patch_text, newline="")
    out = _git(repo, "apply", "--3way", str(tmp_path / "upgrade.patch"), check=False)
    assert out.returncode == 0, out.stderr

    assert (repo / GENERATED_FILE).read_text() == real[GENERATED_FILE]
    merged = (repo / SEEDED_FILE).read_text()
    assert "Owner notes: deploy runs on Fridays." in merged and "OLD seeded title" not in merged
    assert merged.split("\n")[0] == real[SEEDED_FILE].split("\n")[0]
    assert (repo / custom_path).read_text() == owner_custom
    assert not (repo / EXTRA_BASE_FILE).exists()
    assert (repo / NEW_FILE).read_text() == "NEW = True\n"
    for path, content in custom.items():
        if path != custom_path:
            assert (repo / path).read_text() == content


def test_patch_is_identical_on_a_second_build_and_never_names_paths_outside_the_tree(
    trees: tuple[dict[str, str], dict[str, str]],
) -> None:
    _, real = trees
    base = _base({k: v for k, v in real.items() if k != NEW_FILE})
    first = ue.plan_upgrade(base, real).patch_text
    assert first == ue.plan_upgrade(dict(base), dict(real)).patch_text
    named = {line.split(" a/", 1)[1].split(" b/")[0] for line in first.splitlines() if line.startswith("diff --git ")}
    assert named <= set(base) | set(real) and all(ue.safe_path(p) for p in named)


def test_a_conflicting_owner_edit_is_left_for_the_owner_not_overwritten(
    trees: tuple[dict[str, str], dict[str, str]], tmp_path: Path
) -> None:
    _, real = trees
    base = _base({k: v for k, v in real.items() if k != NEW_FILE})
    plan = ue.plan_upgrade(base, real)
    repo = tmp_path / "owner"
    repo.mkdir()
    _git(repo, "init", "-q")
    _write(repo, base)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    lines = base[SEEDED_FILE].split("\n")
    lines[0] = "# OWNER TITLE"  # the same line the upgrade changes
    (repo / SEEDED_FILE).write_text("\n".join(lines), newline="")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "owner")
    (tmp_path / "u.patch").write_text(plan.patch_text, newline="")
    out = _git(repo, "apply", "--3way", str(tmp_path / "u.patch"), check=False)
    merged = (repo / SEEDED_FILE).read_text()
    assert out.returncode != 0 and "<<<<<<<" in merged, out.stderr  # a real 3-way merge: markers, not a clobber
    assert "# OWNER TITLE" in merged and "# OLD seeded title" not in merged


def test_hostile_blob_and_paths_are_refused() -> None:
    import zlib

    with pytest.raises(ue.UpgradeError):
        ue.decode_blob(zlib.compress(json.dumps({"../../etc/cron.d/x": "y"}).encode()))
    with pytest.raises(ue.UpgradeError):
        ue.plan_upgrade({}, {"../x": "y\n"})
    bomb = zlib.compress(b'{"a":"' + b"0" * 20_000_000 + b'"}')
    with pytest.raises(ue.UpgradeError) as err:
        ue.decode_blob(bomb, max_bytes=1_000_000)
    assert err.value.code == "baseline_too_large"
