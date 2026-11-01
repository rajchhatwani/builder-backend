"""Effectful hooks end to end (B2-10): generate the hooks_effects project, migrate a real Postgres, run the project's
own tests, the gate on a real effect body, and the budget / failure-policy scenarios (tests/e2e/hooks_effects_scenarios.py,
copied into the project). Provider emulator only, no network. Needs Docker (testcontainers)."""

from pathlib import Path

from testcontainers.community.postgres import PostgresContainer

from tests.e2e.hooks_support import run_gate, write_body
from tests.e2e.test_generated_project import ok, postgres, project_dir, run  # noqa: F401

HERE = Path(__file__).resolve().parent

BODY = """
from app.platform_sdk import notify, send_email

ok = send_email("buyer@example.com", "Order " + data.reference, "Thanks for your order")
notify("welcome", str(data.id), {"name": data.reference}, email="buyer@example.com")
return AnnounceResult(sent=ok)
"""


def test_effect_hooks_gate_budgets_and_policy(
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory,  # noqa: ANN001
) -> None:
    root = project_dir(tmp_path_factory, "hooks_effects")
    url = (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/hooks_effects_scn_test"
    )
    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    ok(run(["-m", "alembic", "check"], root, url))
    ok(run(["-m", "alembic", "downgrade", "base"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))

    # the stub is not implemented yet, then a real effect body passes every gate
    code, report, _ = run_gate(root)
    assert code == 1 and {f["rule"] for f in report["findings"]} == {"G5.not_implemented"}
    write_body(root, "announce_order", BODY)
    code, report, _ = run_gate(root)
    assert code == 0, report
    write_body(root, "announce_order", "import socket\nreturn AnnounceResult(sent=True)")
    code, report, _ = run_gate(root)
    assert code == 1 and "G1.banned_import" in {f["rule"] for f in report["findings"]}
    write_body(root, "announce_order", BODY)

    full = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider"], root, url))
    assert "passed" in full and "failed" not in full, full
    print("FULL PROJECT:", full.strip().splitlines()[-1])

    (root / "tests" / "test_effects_runtime.py").write_text(
        (HERE / "hooks_effects_scenarios.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    out = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_effects_runtime.py"], root, url, APP_ENV="test"))
    assert "1 passed" in out, out
    print("EFFECT SCENARIOS:", out.strip().splitlines()[-1])
