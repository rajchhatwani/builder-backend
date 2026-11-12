"""CO5-5: the periodic jobs have a deployable entry (compose service, systemd unit, doc)."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_compose_runs_the_scheduler_service() -> None:
    svc = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]["scheduler"]
    assert svc["command"][-2:] == ["-m", "app.jobs.scheduler"]
    assert svc["restart"] == "unless-stopped"


def test_systemd_unit_and_doc_name_the_same_entry_point() -> None:
    unit = (ROOT / "deploy/systemd/builder-scheduler.service").read_text()
    assert "ExecStart=/usr/bin/env uv run python -m app.jobs.scheduler" in unit
    assert "Restart=always" in unit
    assert "app.jobs.scheduler" in (ROOT / "docs/SCHEDULING.md").read_text()


def test_scheduler_jobs_cover_reports_and_idle_sweep() -> None:
    from app.jobs import scheduler

    assert {name for name, _, _ in scheduler.jobs()} == {"reports", "idle_sweep"}
