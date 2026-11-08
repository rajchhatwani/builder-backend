"""Webhooks end to end: generate the `webhooks_orders` project (multi-tenant; events, jobs, providers and webhooks),
migrate a real Postgres (up, check, down, up) and run the project's own tests, which cover the SSRF guard (private
addresses, DNS rebinding, redirects, user-info tricks), signatures, delivery with retries, rotation, auto-disable
and incoming verification. No network: names and sockets are fakes. Needs Docker (testcontainers)."""

from testcontainers.community.postgres import PostgresContainer

from tests.e2e.test_generated_project import ok, postgres, project_dir, run  # noqa: F401


def test_the_webhooks_project_migrates_and_passes_its_own_tests(
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory,  # noqa: ANN001
) -> None:
    root = project_dir(tmp_path_factory, "webhooks_orders")
    url = (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/webhooks_scn_test"
    )
    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    ok(run(["-m", "alembic", "check"], root, url))
    ok(run(["-m", "alembic", "downgrade", "base"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    output = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_webhooks.py"], root, url))
    assert "passed" in output and "failed" not in output, output
    print("WEBHOOK TESTS:", output.strip().splitlines()[-1])
    full = ok(run(["-m", "pytest", "-q", "-p", "no:cacheprovider"], root, url))
    assert "passed" in full and "failed" not in full, full
    print("FULL PROJECT:", full.strip().splitlines()[-1])
