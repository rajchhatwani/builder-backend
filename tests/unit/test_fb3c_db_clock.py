"""A-002 (CO3-4): generated job, outbox and notification workers decide due / lease / retry by the DATABASE
clock, and an idempotent replay re-checks the caller's roles. The behaviour itself is proven by the generated
projects' own tests (test_jobs, test_api_edge); these checks keep the generator from going back to the host
clock or dropping the replay check."""

import re
from pathlib import Path

import pytest

from app.core.generator import generate
from app.core.spec_models import Spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _files(name: str) -> dict[str, str]:
    return generate(Spec.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))


def _body(src: str, fn: str) -> str:
    m = re.search(rf"^async def {fn}\(.*?(?=^(?:async )?def |\Z)", src, re.S | re.M)
    assert m, fn
    return m.group(0)


@pytest.mark.parametrize("fn", ["enqueue", "claim", "complete", "fail", "requeue_dead", "purge_succeeded"])
def test_job_queue_functions_use_the_database_clock(fn: str) -> None:
    src = _files("jobs_invoices")["app/jobs/queue.py"]
    body = _body(src, fn)
    assert "utcnow" not in body and "datetime.now" not in body
    assert "utcnow" not in src  # not even imported


def test_scheduler_asks_the_database_for_the_time() -> None:
    src = _files("jobs_invoices")["app/jobs/scheduler.py"]
    assert "utcnow" not in src and "queue.db_now" in src


def test_outbox_relay_and_notification_claims_use_the_database_clock() -> None:
    relay = _files("events_orders")["app/events/relay.py"]
    assert "utcnow" not in relay and "sa.func.now()" in relay
    outbox = _files("events_orders")["app/events/outbox.py"]
    assert 'next_attempt_at": now' in outbox.replace("  ", " ") or "now = sa.func.now()" in outbox
    notif = _files("notifications_orders")["app/notifications/dispatcher.py"]
    claim = _body(notif, "claim")
    assert "utcnow" not in claim and "sa.func.now()" in claim
    assert "when = utcnow()" not in notif


def test_an_idempotent_replay_checks_the_callers_roles_again() -> None:
    files = _files("api_edge_orders")
    idem = files["app/api_edge/idempotency.py"]
    assert "caller_roles=list(caller.roles)" in idem and "idempotency_access_changed" in idem
    assert "roles=tuple(sorted(" in files["app/api_edge/caller.py"]
    assert "caller_roles" in files["alembic/versions/0012_api_edge.py"]
    assert "caller_roles" in files["app/api_edge/models.py"]
