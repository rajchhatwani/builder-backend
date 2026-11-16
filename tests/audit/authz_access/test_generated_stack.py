"""Hostile access scenarios against a generated project on a real Postgres (Docker, testcontainers).
The scenarios live in generated_scenarios.py and run once inside the generated project; each becomes
its own test here so a failure names the attack."""

import re
import shutil
import xml.etree.ElementTree as ET  # noqa: S405 - our own junit file
from pathlib import Path

import pytest
from testcontainers.community.postgres import PostgresContainer

from tests.e2e.test_generated_project import ok, postgres, project_dir, run  # noqa: F401

HERE = Path(__file__).resolve().parent
SCENARIOS = re.findall(r"^async def (test_\w+)", (HERE / "generated_scenarios.py").read_text(), re.M)


@pytest.fixture(scope="module")
def outcome(
    postgres: PostgresContainer,  # noqa: F811
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, str | None]:
    """name -> None when it passed, else the failure text."""
    root = project_dir(tmp_path_factory, "realtime_metrics")
    shutil.copy(HERE / "generated_scenarios.py", root / "tests" / "test_scenarios.py")
    url = (
        f"postgresql+asyncpg://{postgres.username}:{postgres.password}"
        f"@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/authz_attack_test"
    )
    ok(run(["-m", "tests._prepare_db"], root, url))
    ok(run(["-m", "alembic", "upgrade", "head"], root, url))
    report = root / "report.xml"
    result = run(
        ["-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short", f"--junitxml={report}", "tests/test_scenarios.py"],
        root,
        url,
    )
    assert report.exists(), result.stdout[-3000:] + result.stderr[-2000:]
    out: dict[str, str | None] = {}
    for case in ET.parse(report).getroot().iter("testcase"):  # noqa: S314
        bad = case.find("failure") if case.find("failure") is not None else case.find("error")
        out[case.get("name", "")] = None if bad is None else (bad.get("message") or "")[:600] + (bad.text or "")[-900:]
    return out


@pytest.mark.parametrize("name", SCENARIOS)
def test_generated(name: str, outcome: dict[str, str | None]) -> None:
    assert name in outcome, f"{name} did not run"
    assert outcome[name] is None, outcome[name]
