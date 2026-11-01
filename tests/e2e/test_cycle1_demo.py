"""Cycle 1 owner demo: two neutral example specs (invoice approval, HR leave request) that use everything
Cycle 1 delivers (expressions, state machines, hooks + gate, settings, sequences, lists, change history, seed).
For each spec, on a real Postgres: generate, write the good hook body, run the gate, migrate, `alembic check`,
downgrade/upgrade, run the project's own tests, drive the business story over HTTP (scenario file copied into
the project), then seed twice and check. Set DEMO_TRANSCRIPT_OUT=<file.md> to keep a readable transcript.
Needs Docker (testcontainers)."""

import json
import os
import re
import shutil
from pathlib import Path

from testcontainers.community.postgres import PostgresContainer

from tests.e2e.hooks_support import FIXTURES, generate_tree, run_gate, write_body
from tests.e2e.test_generated_project import ok, postgres, run  # noqa: F401
from tests.e2e.test_hooks_stack import db_url, migrate, write_project

HERE = Path(__file__).resolve().parent

MATCH_INVOICE = """
from decimal import Decimal

from app.platform_sdk import is_blank, pct_diff

if is_blank(data.invoice_no):
    return MatchResult(allowed=False, reason="the invoice number is missing")
if data.amount <= Decimal("0") or data.po_amount <= Decimal("0"):
    return MatchResult(allowed=False, reason="amounts must be positive")
if pct_diff(data.amount, data.po_amount) > Decimal("50"):
    return MatchResult(allowed=False, reason="the invoice differs from its purchase order by more than 50 percent")
return MatchResult(allowed=True)
"""

CHECK_REQUEST = """
from app.platform_sdk import is_blank

if data.days > 5 and is_blank(data.reason):
    return RequestResult(valid=False, message="a reason is required for more than 5 days")
return RequestResult(valid=True)
"""

DEMOS = {
    "demo_invoice": {
        "hook": "match_invoice",
        "good": MATCH_INVOICE,
        "bad": ("import os\nreturn MatchResult(allowed=True)", "G1.banned_import"),
        "scenarios": "demo_invoice_scenarios.py",
    },
    "demo_leave": {
        "hook": "check_request",
        "good": CHECK_REQUEST,
        "bad": ("import socket\nreturn RequestResult(valid=True)", "G1.banned_import"),
        "scenarios": "demo_leave_scenarios.py",
    },
}


def counts(output: str) -> str:
    match = re.findall(r"(\d+ passed(?:, \d+ \w+)*)", output)
    assert match, output
    return match[-1]


def run_demo(name: str, postgres: PostgresContainer, tmp_path_factory) -> list[str]:  # noqa: ANN001, F811
    demo = DEMOS[name]
    hook = demo["hook"]
    spec = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    out = [f"## {name}", ""]
    root = write_project(tmp_path_factory.mktemp(name), generate_tree(spec))
    out.append(f"generated {sum(1 for p in root.rglob('*') if p.is_file())} files; hook stub: app/custom/hooks/{hook}.py")
    url = db_url(postgres, f"{name}_test")

    # 1. the gate: the untouched stub is refused; a banned import is refused with its rule id; the good body passes
    code, report, _ = run_gate(root)
    assert code == 1 and {f["rule"] for f in report["findings"]} == {"G5.not_implemented"}
    out.append("gate on the untouched stub: exit 1 (G5.not_implemented)")
    bad_body, rule = demo["bad"]
    write_body(root, hook, bad_body)
    code, report, summary = run_gate(root)
    assert code == 1 and rule in {f["rule"] for f in report["findings"]}, summary
    out.append(f"gate on a body with a banned import: exit {code} -> {summary.strip().splitlines()[-1] if summary.strip() else rule}")
    out.append(f"  rule ids reported: {sorted({f['rule'] for f in report['findings']})}")
    write_body(root, hook, demo["good"])
    code, report, summary = run_gate(root)
    assert code == 0 and report["ok"] is True and report["findings"] == [], summary
    assert {g["status"] for g in report["gates"].values()} == {"pass"}
    out.append(f"gate on the good body: exit 0, gates {sorted(report['gates'])} all pass, hooks {sorted(report['hooks'])}")

    # 2. migrations
    migrate(root, url)
    out.append("migrate: _prepare_db, alembic upgrade head, alembic check, downgrade base, upgrade head: all exit 0")

    # 3. the project's own tests, then the business story over HTTP
    own = counts(ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider"], root, url)))
    assert "failed" not in own
    out.append(f"project's own tests: {own}")
    shutil.copy(HERE / demo["scenarios"], root / "tests" / "test_scenarios.py")
    story = counts(ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_scenarios.py"], root, url)))
    assert "failed" not in story
    out.append(f"business scenarios (tests/test_scenarios.py): {story}")
    log = (root / "demo_transcript.log").read_text(encoding="utf-8")
    out += ["", "### Business story (real output of the scenario run)", "```", *sorted_story(log), "```", ""]

    # 4. seed: clean schema, demo twice, check, then the dev profile
    ok(run(["-m", "alembic", "downgrade", "base"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    env = {"APP_ENV": "development"}
    first = ok(run(["-m", "app.seed", "--profile", "demo"], root, url, **env))
    second = ok(run(["-m", "app.seed", "--profile", "demo"], root, url, **env))
    digest = [line for line in first.splitlines() if line.startswith("digest:")]
    assert digest and digest == [line for line in second.splitlines() if line.startswith("digest:")]
    assert "already_seeded" in second and "already_seeded" not in first
    check = ok(run(["-m", "app.seed", "--check"], root, url, **env))
    assert "all invariants hold" in check
    out += ["### Seed (python -m app.seed)", "```", "$ --profile demo", first.strip(), "$ --profile demo   (second run)",
            second.strip(), "$ --check", check.strip()]
    dev = ok(run(["-m", "app.seed", "--profile", "dev", "--reset"], root, url, **env))
    assert "all invariants hold" in ok(run(["-m", "app.seed", "--check"], root, url, **env))
    out += ["$ --profile dev --reset", dev.strip(), "$ --check", "all invariants hold", "```", ""]
    return out


def sorted_story(log: str) -> list[str]:
    """pytest runs the scenarios in file order, so the log is already in story order."""
    return [line for line in log.splitlines() if line.strip()]


def test_invoice_approval_demo(postgres: PostgresContainer, tmp_path_factory) -> None:  # noqa: ANN001, F811
    transcript = run_demo("demo_invoice", postgres, tmp_path_factory)
    keep(transcript, "demo_invoice")


def test_leave_request_demo(postgres: PostgresContainer, tmp_path_factory) -> None:  # noqa: ANN001, F811
    transcript = run_demo("demo_leave", postgres, tmp_path_factory)
    keep(transcript, "demo_leave")


def keep(lines: list[str], name: str) -> None:
    target = os.environ.get("DEMO_TRANSCRIPT_OUT")
    if target:
        Path(f"{target}.{name}.part").write_text("\n".join(lines) + "\n", encoding="utf-8")
