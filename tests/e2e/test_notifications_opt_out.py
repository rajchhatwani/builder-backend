"""A-006: an opted-out user receives nothing. Generates the notifications project, migrates a real Postgres and
runs the generated opt-out tests (which send through the provider emulator and assert the delivery row is
`suppressed`/`opt_out` with no address and no body, and that the emulator recorded nothing). The generated
tests skip themselves when the spec has no optional type; here a skip is a failure, so the guard cannot go
silent. Needs Docker (testcontainers)."""

import re

import pytest
from testcontainers.community.postgres import PostgresContainer

from tests.e2e.test_generated_project import ok, postgres, project_dir, run  # noqa: F401

OPT_OUT_TESTS = (
    "test_an_opt_out_is_honoured_and_logged",
    "test_an_opt_out_made_after_queueing_stops_the_send",
    "test_opting_back_in_and_one_channel_only",
)


def test_an_opted_out_user_receives_nothing(
    postgres: PostgresContainer, tmp_path_factory: pytest.TempPathFactory  # noqa: F811
) -> None:
    root = project_dir(tmp_path_factory, "notifications_orders")
    url = (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/optout_test"
    )
    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    selector = " or ".join(OPT_OUT_TESTS)
    out = ok(run(["-m", "pytest", "-v", "-rs", "-p", "no:cacheprovider", "tests/test_notifications.py", "-k", selector], root, url))
    for name in OPT_OUT_TESTS:
        assert re.search(rf"{name}\S* PASSED", out), f"{name} did not run and pass:\n{out}"
    assert "SKIPPED" not in out and "skipped" not in out
