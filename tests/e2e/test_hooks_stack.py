"""Custom hooks end to end: generate the example projects, migrate a real Postgres, run the project's own
tests, the gate on the hook bodies, and the scenario files in tests/e2e/. Needs Docker (testcontainers)."""

import json
import shutil
from pathlib import Path

from testcontainers.community.postgres import PostgresContainer

from tests.e2e.hooks_support import (
    BODIES,
    example_spec,
    generate_tree,
    points_spec,
    run_gate,
    write_body,
    write_good_bodies,
)
from tests.e2e.test_generated_project import ok, postgres, run  # noqa: F401

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "fixtures" / "specs"


def write_project(root: Path, files: dict[str, str]) -> Path:
    for path, content in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return root


def db_url(postgres: PostgresContainer, name: str) -> str:  # noqa: F811
    return (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/{name}"
    )


def migrate(root: Path, url: str) -> None:
    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    ok(run(["-m", "alembic", "check"], root, url))
    ok(run(["-m", "alembic", "downgrade", "base"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))


def test_the_invoice_example_gates_and_runtime(
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory,  # noqa: ANN001
) -> None:
    root = write_project(tmp_path_factory.mktemp("hooks_invoice"), generate_tree(example_spec()))
    url = db_url(postgres, "hooks_invoice_scn_test")
    migrate(root, url)

    # 1. a fresh project: the generated contract tests and the project's own tests pass with the stubs untouched
    output = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider"], root, url))
    assert "passed" in output and "failed" not in output

    # 2. the gate: the stub is not implemented yet (reported, exit 1)
    code, report, _ = run_gate(root)
    assert code == 1 and {f["rule"] for f in report["findings"]} == {"G5.not_implemented"}

    # 3. a banned import is rejected with its rule id, in whole-project mode and in single-file mode
    write_body(root, "match_invoice", "import os\nreturn MatchResult(allowed=True)")
    code, report, summary = run_gate(root)
    rules = {f["rule"] for f in report["findings"]}
    assert code == 1 and "G1.banned_import" in rules and "G1.banned_import" in summary
    assert report["gates"]["G1"]["status"] == "fail" and report["gate_version"] == 2
    assert all(g["means"] for g in report["gates"].values())
    code, report, _ = run_gate(root, "--file", "app/custom/hooks/match_invoice.py")
    assert code == 1 and any(f["rule"] == "G1.banned_import" and f["line"] == 8 for f in report["findings"])

    # 3b. the module-alias escape found by SENTINEL (B-1) is rejected with its rule id, and so are
    #     getattr/format (B-2), `re` and an unbounded iterator (M-1)
    b1 = (
        "import calendar\nc = calendar\n"
        'out = c.sys.modules["os"].popen("echo RCE; id -u").read()\n'
        "return MatchResult(allowed=True, reason=out)"
    )
    for body, expected in (
        (b1, "G1.module_value"),
        ('getattr("{0.__init__.__globals__[sys]}", "format")(data)\nreturn MatchResult(allowed=True)', "G2.format_string"),
        ('import re\nre.match(r"(a+)+$", "a" * 32 + "b")\nreturn MatchResult(allowed=True)', "G1.banned_import"),
        ("for _ in iter(int, 1):\n    pass\nreturn MatchResult(allowed=True)", "G6.unbounded"),
    ):
        write_body(root, "match_invoice", body)
        code, report, summary = run_gate(root, "--hook", "match_invoice")
        assert code == 1 and expected in {f["rule"] for f in report["findings"]}, (expected, summary)
        assert expected in summary

    # 4. good bodies: G0-G7 all pass, exit 0
    write_good_bodies(root, ["match_invoice", "notify_approved"])
    code, report, summary = run_gate(root)
    assert code == 0, summary
    assert report["ok"] is True and report["findings"] == []
    assert {g["status"] for g in report["gates"].values()} == {"pass"}

    # 4b. G7 also guards alembic, dependency lists, conftest/site hooks and .pth files
    (root / "evil.pth").write_text("import os\n", encoding="utf-8")
    (root / "alembic" / "versions" / "9999_evil.py").write_text("x = 1\n", encoding="utf-8")
    code, report, _ = run_gate(root)
    assert code == 1 and {f["rule"] for f in report["findings"]} == {"G7.guarded_new_file"}
    (root / "evil.pth").unlink()
    (root / "alembic" / "versions" / "9999_evil.py").unlink()
    code, report, summary = run_gate(root)
    assert code == 0, summary

    # 5. the guard and the effect on a running app
    shutil.copy(HERE / "hooks_scenarios.py", root / "tests" / "test_scenarios.py")
    output = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider"], root, url))
    assert "passed" in output and "failed" not in output


def test_hooks_at_every_point_of_the_chain(
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory,  # noqa: ANN001
) -> None:
    root = write_project(tmp_path_factory.mktemp("hooks_points"), generate_tree(points_spec()))
    url = db_url(postgres, "hooks_points_scn_test")
    migrate(root, url)
    write_good_bodies(root, list(BODIES))
    code, report, summary = run_gate(root)
    assert code == 0, summary
    assert len(report["hooks"]) == 6
    shutil.copy(HERE / "hooks_points_scenarios.py", root / "tests" / "test_scenarios.py")
    output = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider"], root, url))
    assert "passed" in output and "failed" not in output


def _access_project(name: str, scenarios: str, postgres, tmp_path_factory) -> None:  # noqa: ANN001
    """A project whose hook reads entities under access rules: the gate passes on the stub bodies being
    replaced by the scenario's own patched functions, and the scenarios prove `find_rows` follows the rules."""
    spec = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    root = write_project(tmp_path_factory.mktemp(name), generate_tree(spec))
    url = db_url(postgres, f"{name}_scn_test")
    migrate(root, url)
    write_body(root, "peek", "return PeekResult(seen=True)")
    code, report, summary = run_gate(root)
    assert code == 0, summary
    shutil.copy(HERE / scenarios, root / "tests" / "test_scenarios.py")
    output = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider"], root, url))
    assert "passed" in output and "failed" not in output


def test_find_rows_follows_role_owner_and_tenant_rules(
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory,  # noqa: ANN001
) -> None:
    _access_project("hooks_access", "hooks_access_scenarios.py", postgres, tmp_path_factory)


def test_find_rows_follows_abac_policies(
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory,  # noqa: ANN001
) -> None:
    _access_project("hooks_access_abac", "hooks_access_abac_scenarios.py", postgres, tmp_path_factory)
