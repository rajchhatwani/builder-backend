"""A-010: the e2e skip policy (tests/e2e/conftest.py) and its end-to-end behaviour in a throwaway pytest run."""

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFTEST = ROOT / "tests" / "e2e" / "conftest.py"


def _policy():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("e2e_conftest_policy", CONFTEST)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_with_runsc_present_a_sandbox_skip_is_unexpected() -> None:
    p = _policy()
    assert p.is_unexpected_sandbox_skip("test_sandbox_hostile.py", "needs docker with the runsc runtime", True, True)
    assert p.is_unexpected_sandbox_skip("test_preview_stack.py", "whatever", True, True)
    assert p.is_unexpected_sandbox_skip(
        "test_preview_stack.py", p.IMAGE_REASON, True, True
    )  # image is there: no excuse


def test_the_excusable_skips() -> None:
    p = _policy()
    assert not p.is_unexpected_sandbox_skip("test_sandbox_hostile.py", "needs docker", False, False)  # no runsc
    assert not p.is_unexpected_sandbox_skip("test_preview_stack.py", p.IMAGE_REASON, True, False)  # image absent
    assert not p.is_unexpected_sandbox_skip("test_storage_stack.py", "needs docker", True, True)  # not a sandbox file


def test_a_skipped_e2e_test_is_listed_with_its_reason_in_the_summary(tmp_path: Path) -> None:
    pkg = tmp_path / "tests" / "e2e"
    pkg.mkdir(parents=True)
    (pkg / "conftest.py").write_text(CONFTEST.read_text(encoding="utf-8"), encoding="utf-8")
    (pkg / "test_demo.py").write_text(
        textwrap.dedent(
            """
            import pytest
            pytestmark = pytest.mark.skipif(True, reason="needs docker with the thing")
            def test_a(): pass
            def test_b(): pass
            """
        ),
        encoding="utf-8",
    )
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(pkg)],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert "SKIPPED [2]" in done.stdout and "needs docker with the thing" in done.stdout, done.stdout


def test_an_unexpected_sandbox_skip_fails_when_runsc_is_present(tmp_path: Path) -> None:
    pkg = tmp_path / "tests" / "e2e"
    pkg.mkdir(parents=True)
    text = CONFTEST.read_text(encoding="utf-8").replace("def runsc_available() -> bool:\n", "def runsc_available() -> bool:\n    return True\n", 1)
    (pkg / "conftest.py").write_text(text, encoding="utf-8")
    (pkg / "test_sandbox_hostile.py").write_text(
        "import pytest\n\n@pytest.mark.skip(reason='silent skip')\ndef test_x(): pass\n", encoding="utf-8"
    )
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(pkg)],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert done.returncode != 0 and "unexpected skip in a sandbox suite" in done.stdout, done.stdout
