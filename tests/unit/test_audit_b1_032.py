"""B1-032: log redaction by key at the top level, bounded availability work, capacity range cap,
no cancelling a started confirmed booking, many_to_many id cap (generated code)."""

import json
import re
import sys
import time
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.generator import generate
from app.core.spec_models import Spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _files(name: str) -> dict[str, str]:
    return generate(
        Spec.model_validate(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))
    )


def _load(files: dict[str, str], path: str, mod: str) -> types.ModuleType:
    module = types.ModuleType(mod)
    sys.modules[mod] = module
    try:
        exec(compile(files[path], path, "exec"), module.__dict__)  # noqa: S102
    finally:
        sys.modules.pop(mod, None)
    return module


@pytest.fixture(scope="module")
def booking_files() -> dict[str, str]:
    return _files("booking_clinic")


@pytest.fixture(scope="module")
def rules(booking_files: dict[str, str]) -> types.ModuleType:
    return _load(booking_files, "app/booking/rules.py", "app.booking.rules")


def test_f1039_top_level_secret_named_log_fields_are_replaced_wholesale() -> None:
    redact = _load(_files("authz_abac"), "app/core/redact.py", "app.core.redact")
    out = redact.redact_processor(
        None, "i", {"event": "x", "password": "hunter2", "token": "abc", "n": 1}
    )
    assert out["password"] == redact.REDACTED
    assert out["token"] == redact.REDACTED
    assert out["n"] == 1 and out["event"] == "x"


def test_f1040_free_slots_is_fast_for_a_dense_month_and_still_correct(
    rules: types.ModuleType,
) -> None:
    t0 = datetime(2030, 1, 1, tzinfo=UTC)
    step = timedelta(minutes=5)
    slots = [(t0 + i * step, t0 + (i + 1) * step) for i in range(8900)]
    start = time.perf_counter()
    marked = rules.free_slots(slots, list(slots))
    assert time.perf_counter() - start < 0.5
    assert not any(free for _, _, free in marked)
    # correctness: partial overlaps, touching ranges, unsorted busy, one long interval
    s = [(t0 + i * step, t0 + (i + 1) * step) for i in range(6)]
    one = timedelta(minutes=1)
    b = [(t0 + 4 * step + one, t0 + 5 * step + one), (t0, t0 + one)]
    assert [f for _, _, f in rules.free_slots(s, b)] == [False, True, True, True, False, False]
    long = [(t0 + step, t0 + 3 * step), (t0 + 2 * step, t0 + 2 * step + one)]
    assert [f for _, _, f in rules.free_slots(s, long)] == [True, False, False, True, True, True]


def test_f1041_capacity_range_is_capped(booking_files: dict[str, str]) -> None:
    service = booking_files["app/booking/service.py"]
    body = service.split("async def capacity(")[1].split("# --- create")[0]
    assert "MAX_AVAILABILITY_DAYS" in body
    assert body.index("MAX_AVAILABILITY_DAYS") < body.index("_active_intervals")


def test_f1042_started_confirmed_booking_cannot_be_cancelled(
    rules: types.ModuleType, booking_files: dict[str, str]
) -> None:
    now = datetime(2030, 1, 1, 12, tzinfo=UTC)
    assert not rules.can_cancel_now("confirmed", now - timedelta(minutes=1), now)
    assert not rules.can_cancel_now("confirmed", now, now)
    assert rules.can_cancel_now("confirmed", now + timedelta(minutes=1), now)
    assert rules.can_cancel_now("held", now - timedelta(minutes=1), now)
    cancel = booking_files["app/booking/service.py"].split("async def cancel_booking(")[1]
    assert "can_cancel_now" in cancel.split("cancellation_fee")[0]


def test_f1043_many_to_many_id_lists_are_capped() -> None:
    files = _files("blog")
    schemas = "\n".join(v for k, v in files.items() if k.startswith("app/schemas"))
    assert "list[_uuid.UUID]" in schemas
    assert re.search(
        r"list\[_uuid\.UUID\] = _pd\.Field\(default_factory=list, max_length=\d+\)", schemas
    )
    assert re.search(
        r"list\[_uuid\.UUID\] \| None = _pd\.Field\(default=None, max_length=\d+\)", schemas
    )


def test_f1045_generated_change_history_tests_cover_recording_and_purge() -> None:
    text = _files("history_notes")["tests/test_change_history.py"]
    for needle in ("record", "purge", "actor", "retention_days", "view_roles"):
        assert needle in text
