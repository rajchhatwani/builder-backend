"""A-005: the regression manifest cannot drift. Every tests/**/test_*.py file (except the golden snapshots) must be
in tests/regression_manifest.txt (as a file or a node id of it) or in tests/manifest_allowlist.txt with a reason."""

from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
ROOT = TESTS.parent


def _lines(path: Path) -> list[str]:
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")]


def _all_test_files() -> set[str]:
    return {
        p.relative_to(ROOT).as_posix()
        for p in TESTS.rglob("test_*.py")
        if "golden" not in p.relative_to(TESTS).parts and "__pycache__" not in p.parts
    }


def _manifest_files() -> set[str]:
    return {ln.split("::")[0] for ln in _lines(TESTS / "regression_manifest.txt")}


def _allowed() -> dict[str, str]:
    out: dict[str, str] = {}
    for ln in _lines(TESTS / "manifest_allowlist.txt"):
        path, _, reason = ln.partition("#")
        out[path.strip()] = reason.strip()
    return out


def test_every_test_file_is_in_the_manifest_or_explicitly_allowed() -> None:
    listed = _manifest_files() | set(_allowed())
    missing = sorted(_all_test_files() - listed)
    assert not missing, (
        "add to tests/regression_manifest.txt (or to tests/manifest_allowlist.txt with a reason):\n" + "\n".join(missing)
    )


def test_allow_list_entries_have_a_reason_and_exist() -> None:
    for path, reason in _allowed().items():
        assert reason, f"{path}: an allow-list entry needs a reason after '#'"
        assert (ROOT / path).is_file(), f"{path} no longer exists: remove it from the allow-list"
        assert path not in _manifest_files(), f"{path} is both in the manifest and the allow-list"


def test_manifest_entries_point_at_real_files() -> None:
    for path in sorted(_manifest_files()):
        assert (ROOT / path).exists(), f"manifest lists {path}, which does not exist"
