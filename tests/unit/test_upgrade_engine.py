"""CP-6E: pure upgrade planner, patch builder, semver, SBOM diff, automerge rule, blob hardening."""

import json
import zlib

import pytest

from app.core import upgrade_engine as ue

CUSTOM = "app/hooks/mine.py"


def _plan(base: dict[str, str], new: dict[str, str]) -> ue.UpgradePlan:
    return ue.plan_upgrade(base, new)


def test_zone_rules_custom_never_in_patch_or_files() -> None:
    base = {"app/main.py": "a\n", "README.md": "one\n", CUSTOM: "mine\n"}
    new = {"app/main.py": "b\n", "README.md": "two\n", CUSTOM: "stub\n", "app/hooks/new.py": "x\n"}
    plan = _plan(base, new)
    zones = {f["path"]: (f["zone"], f["change"]) for f in plan.files}
    assert zones == {"app/main.py": ("generated", "modified"), "README.md": ("seeded", "modified")}
    assert plan.kept == ["app/hooks/mine.py", "app/hooks/new.py"]
    assert "app/hooks" not in plan.patch_text and "mine" not in plan.patch_text


def test_added_removed_and_unchanged() -> None:
    base = {"gone.py": "x\n", "same.py": "s\n"}
    new = {"fresh.py": "y\n", "same.py": "s\n"}
    plan = _plan(base, new)
    assert {(f["path"], f["change"]) for f in plan.files} == {("gone.py", "removed"), ("fresh.py", "added")}
    assert "new file mode 100644" in plan.patch_text and "deleted file mode 100644" in plan.patch_text
    assert "--- /dev/null" in plan.patch_text and "+++ /dev/null" in plan.patch_text
    assert "same.py" not in plan.patch_text


def test_patch_is_deterministic_and_git_shaped() -> None:
    base = {"b.py": "1\n2\n3\n", "a.py": "x"}
    new = {"b.py": "1\n2\n4\n", "a.py": "x\n"}
    first, second = _plan(base, new).patch_text, _plan(dict(reversed(base.items())), dict(reversed(new.items()))).patch_text
    assert first == second
    assert first.index("diff --git a/a.py") < first.index("diff --git a/b.py")
    assert f"index {ue.git_blob_hash('1\n2\n3\n')}..{ue.git_blob_hash('1\n2\n4\n')} 100644" in first
    assert "\\ No newline at end of file" in first  # a.py lost its missing final newline


def test_equal_trees_give_empty_plan() -> None:
    plan = _plan({"a": "1"}, {"a": "1"})
    assert plan.empty and plan.patch_text == "" and plan.files == []


def test_carriage_return_is_not_a_line_break() -> None:
    plan = _plan({"w.txt": "a\r\nb\r\n"}, {"w.txt": "a\r\nc\r\n"})
    assert "-b\r\n" in plan.patch_text and "+c\r\n" in plan.patch_text


@pytest.mark.parametrize("path", ["../evil", "/etc/passwd", "a/../b", "a b", "a\\b", "a\nb", "./x", "a//b", ""])
def test_unsafe_paths_never_reach_a_patch(path: str) -> None:
    assert not ue.safe_path(path)
    with pytest.raises(ue.UpgradeError):
        ue.file_diff(path, None, "x\n")
    with pytest.raises(ue.UpgradeError):
        _plan({}, {path: "x\n"})


@pytest.mark.parametrize(
    ("old", "new", "bump"),
    [
        ("1.0.0", "1.0.1", "patch"), ("1.0.0", "1.1.0", "minor"), ("1.9.9", "2.0.0", "major"),
        ("1.0.0", "1.0.0", None), (None, "1.0.0", "minor"), ("1.0.0", None, "major"),
        ("1.2.0", "1.1.0", "major"), ("weird", "1.0.0", "major"),
    ],
)
def test_classify_bump(old: str | None, new: str | None, bump: str | None) -> None:
    assert ue.classify_bump(old, new) == bump


def test_block_changes_sorted() -> None:
    out = ue.block_changes({"a": "1.0.0", "b": "1.0.0"}, {"a": "1.0.1", "b": "1.0.0", "c": "0.1.0"})
    assert out == [
        {"block": "a", "from": "1.0.0", "to": "1.0.1", "bump": "patch"},
        {"block": "c", "from": None, "to": "0.1.0", "bump": "minor"},
    ]


def _g(path: str = "app/x.py") -> list[dict[str, str]]:
    return [{"path": path, "zone": "generated", "change": "modified"}]


def _c(bump: str) -> list[dict[str, str]]:
    return [{"block": "crud", "from": "1.0.0", "to": "1.0.1", "bump": bump}]


def test_auto_apply_patch_and_passing_yes() -> None:
    assert ue.auto_apply_eligible(_c("patch"), _g(), [], True) is True


def test_auto_apply_major_never_even_when_passing() -> None:
    assert ue.auto_apply_eligible(_c("major"), _g(), [], True) is False
    assert ue.auto_apply_eligible(_c("major") + _c("patch"), _g(), [], True) is False


def test_auto_apply_minor_no() -> None:
    assert ue.auto_apply_eligible(_c("minor"), _g(), [], True) is False


def test_auto_apply_failing_scorecard_no() -> None:
    assert ue.auto_apply_eligible(_c("patch"), _g(), [], False) is False


def test_auto_apply_no_block_change_only_generated_edits() -> None:
    assert ue.auto_apply_eligible([], _g(), [], True) is True
    seeded = [{"path": "README.md", "zone": "seeded", "change": "modified"}]
    assert ue.auto_apply_eligible([], seeded, [], True) is False
    assert ue.auto_apply_eligible([], [], [], True) is False


def test_auto_apply_never_with_a_migration() -> None:
    assert ue.auto_apply_eligible(_c("patch"), _g(), [{"path": "alembic/versions/x.py", "change": "added"}], True) is False


def test_sbom_diff_requirements_and_pyproject() -> None:
    base = {
        "requirements.txt": "fastapi==0.110.0\nuvicorn[standard]==0.29.0  # srv\n--hash x\nold-pkg==1\n",
        "pyproject.toml": '[project]\ndependencies = ["pydantic>=2.0"]\n',
    }
    new = {
        "requirements.txt": "fastapi==0.111.0\nuvicorn[standard]==0.29.0\nnew_pkg==2.0\n",
        "pyproject.toml": '[project]\ndependencies = ["pydantic>=2.0"]\n',
    }
    diff = ue.sbom_diff(base, new)
    assert diff["added"] == [{"name": "new-pkg", "spec": "==2.0"}]
    assert diff["removed"] == [{"name": "old-pkg", "spec": "==1"}]
    assert diff["changed"] == [{"name": "fastapi", "from": "==0.110.0", "to": "==0.111.0"}]


def test_migrations_listed_from_changed_files() -> None:
    plan = _plan({}, {"alembic/versions/0100_x.py": "x\n", "app/y.py": "y\n"})
    assert plan.migrations == [{"path": "alembic/versions/0100_x.py", "change": "added"}]


def test_blob_round_trip_drops_custom_zone() -> None:
    tree = {"app/main.py": "m\n", CUSTOM: "secret owner code\n"}
    blob = ue.encode_blob(tree)
    assert b"owner code" not in zlib.decompress(blob)
    assert ue.decode_blob(blob) == {"app/main.py": "m\n"}


def test_blob_bomb_is_bounded() -> None:
    bomb = zlib.compress(json.dumps({"a.txt": "0" * 5_000_000}).encode())
    assert len(bomb) < 20_000
    with pytest.raises(ue.UpgradeError) as err:
        ue.decode_blob(bomb, max_bytes=1_000_000)
    assert err.value.code == "baseline_too_large"
    assert ue.decode_blob(bomb, max_bytes=10_000_000)["a.txt"].startswith("000")


@pytest.mark.parametrize(
    "payload",
    [b"not zlib", zlib.compress(b"[1,2]"), zlib.compress(b'{"a": 1}'), zlib.compress(b'{"../x": "y"}'), zlib.compress(b"\xff\xfe")],
)
def test_blob_garbage_and_hostile_paths_refused(payload: bytes) -> None:
    with pytest.raises(ue.UpgradeError) as err:
        ue.decode_blob(payload)
    assert err.value.code == "baseline_unreadable"


def test_auto_apply_refuses_dependency_changes_removed_files_and_prereleases() -> None:
    f_gen = [{"path": "app/x.py", "zone": "generated", "change": "modified"}]
    assert ue.auto_apply_eligible([], f_gen, [], True) is True
    assert ue.auto_apply_eligible([], f_gen, [], True, sbom={"changed": [{"name": "a"}], "added": [], "removed": []}) is False
    gone = [{"path": "app/x.py", "zone": "generated", "change": "removed"}]
    assert ue.auto_apply_eligible([], gone, [], True) is False
    assert ue.auto_apply_eligible([], f_gen, [], True, generator_bump="minor") is False
    assert ue.classify_bump("1.0.0", "1.0.0-rc1") == "major"
