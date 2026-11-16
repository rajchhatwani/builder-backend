"""Audit B1-009: event order, seq high-water mark and the generated document/job tests."""

import re
from pathlib import Path

from app.core.generator import generate
from app.core.spec_models import Spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _files(name: str) -> dict[str, str]:
    text = (FIXTURES / f"{name}.json").read_text(encoding="utf-8")
    return generate(Spec.model_validate_json(text))


def test_f0317_auto_transition_events_are_written_after_the_entity_event() -> None:
    src = _files("events_orders")["app/events/hooks.py"]
    # the listener defers the transition event while the entity hook flushes ...
    assert "_DEFERRED" in src
    listener = src[src.index("def _announce_transition"):]
    assert "_DEFERRED.get()" in listener
    # ... and record() writes the entity event BEFORE draining the deferred transition events
    record = src[src.index("async def record"):src.index("return {\"before_save\"")]
    assert record.index("_DEFERRED.set") < record.index("session.flush()")
    assert record.index(".created") < record.index("_write_deferred")
    assert record.index(".updated") < record.rindex("_write_deferred")


def test_f0317_generated_test_covers_an_auto_transition_on_create() -> None:
    src = _files("events_orders")["tests/test_events.py"]
    assert "auto_transition" in src


def test_f0318_purge_keeps_the_highest_seq_of_every_aggregate() -> None:
    src = _files("events_orders")["app/events/outbox.py"]
    purge = src[src.index("async def purge_delivered"):src.index("async def requeue_failed")]
    assert "sa.func.max(" in purge  # a high-water mark survives the purge
    tests = _files("events_orders")["tests/test_events.py"]
    assert "seq_never_restarts" in tests


def test_f0319_the_db_clock_test_really_skews_the_host_clock() -> None:
    src = _files("jobs_invoices")["tests/test_jobs.py"]
    body = src[src.index("def test_scheduling_and_leases_use_the_database_clock"):]
    body = body[: body.index("# --- exactly once")]
    assert "hasattr" not in body
    assert "_dt" in body  # the modules' datetime is replaced by a skewed one
    assert "skewed" in body and "is_skewed" in body  # and the skew is proven to be active


def test_f0320_markup_test_demands_the_literal_markup_in_the_text() -> None:
    src = _files("docs_desk")["tests/test_documents.py"]
    body = src[src.index("def test_data_can_never_inject_markup"):]
    body = body[: body.index("def test_totals_are_recomputed")]
    assert "not in text.replace" not in body
    assert '"<b>bold</b>" in text' in body or "'<b>bold</b>' in text" in body


def test_f0321_bound_templates_are_rendered_from_a_real_record() -> None:
    src = _files("tenant_guard")["tests/test_documents.py"]
    assert "_factories.make_employees" in src
    assert "SHADOWED" in src  # `extra` must not change the row values
    assert re.search(r"assert .* in text_of\(", src) or "in text" in src


def test_f0318_seq_mark_is_bounded_and_purge_test_ages_past_it() -> None:
    files = _files("events_orders")
    purge = files["app/events/outbox.py"]
    purge = purge[purge.index("async def purge_delivered"):purge.index("async def requeue_failed")]
    assert "OutboxEvent.delivered_at >= marker_cutoff" in purge  # a mark is not kept forever
    tests = files["tests/test_events.py"]
    assert "test_the_seq_mark_is_dropped_after_twice_the_retention" in tests
    assert "timedelta(days=40)" in tests  # the old purge test ages past 2x the retention
