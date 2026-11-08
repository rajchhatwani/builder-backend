"""e2e test plumbing (A-010): skips must be visible, and a sandbox skip must never hide a real failure.

* Every skipped e2e test is listed with its reason in the terminal summary, whether or not `-rs` was given,
  so a gate log shows "9 skipped: needs docker with the runsc runtime" instead of a silent green.
* The sandbox suites (gVisor / preview) are the only evidence for the isolation and resource limits. When
  runsc IS available on this machine, a skip in those files is turned into a failure: the environment is
  capable, so the test must run. The only tolerated skip is the preview stack's own image prerequisite.
"""

import shutil
import subprocess
from functools import cache

import pytest

SANDBOX_FILES = frozenset({"test_sandbox_hostile.py", "test_preview_stack.py"})
PREVIEW_IMAGE = "bb-preview-app:1"
IMAGE_REASON = "needs docker + runsc + the bb-preview-app:1 image"


@cache
def runsc_available() -> bool:
    if shutil.which("docker") is None:
        return False
    out = subprocess.run(["docker", "info", "--format", "{{json .Runtimes}}"], capture_output=True, text=True)
    return out.returncode == 0 and "runsc" in out.stdout


@cache
def preview_image_present() -> bool:
    return subprocess.run(["docker", "image", "inspect", PREVIEW_IMAGE], capture_output=True).returncode == 0


def is_unexpected_sandbox_skip(file_name: str, reason: str, runsc: bool, image: bool) -> bool:
    """True when a skip in a sandbox suite should fail: runsc is present, so nothing excuses it."""
    if file_name not in SANDBOX_FILES or not runsc:
        return False
    return not (reason == IMAGE_REASON and not image)


def _reason(report: pytest.TestReport) -> str:
    longrepr = report.longrepr
    text = longrepr[2] if isinstance(longrepr, tuple) else str(longrepr)
    return text.removeprefix("Skipped: ")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):  # type: ignore[no-untyped-def]
    outcome = yield
    report: pytest.TestReport = outcome.get_result()
    if not report.skipped or item.path.name not in SANDBOX_FILES:
        return
    reason = _reason(report)
    runsc = runsc_available()
    if is_unexpected_sandbox_skip(item.path.name, reason, runsc, runsc and preview_image_present()):
        report.outcome = "failed"
        report.longrepr = (
            f"unexpected skip in a sandbox suite although runsc is available: {reason!r}. "
            "These tests prove the isolation limits and must run on this machine."
        )


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    groups: dict[tuple[str, str], int] = {}
    for report in terminalreporter.stats.get("skipped", []):
        if "tests/e2e/" not in report.nodeid.replace("\\", "/") and not report.nodeid.startswith("e2e/"):
            continue
        key = (report.nodeid.split("::")[0], _reason(report))
        groups[key] = groups.get(key, 0) + 1
    if not groups:
        return
    terminalreporter.section("e2e skipped (reasons)")
    for (path, reason), count in sorted(groups.items()):
        terminalreporter.write_line(f"SKIPPED [{count}] {path}: {reason}")
