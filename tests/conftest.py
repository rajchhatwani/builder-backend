"""Gate helper: with GATE_FAIL_LOG=<file> every failing test id is appended to that file, because
scripts/gate.sh prints only a summary line (CP-4E's four manifest failures were never named)."""

import os


def pytest_runtest_logreport(report):  # noqa: ANN001, ANN201
    path = os.environ.get("GATE_FAIL_LOG")
    if path and report.failed:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{report.when} {report.nodeid}\n")
