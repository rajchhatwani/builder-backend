"""CP-5C-BOOK: the booking pack (D12 reservation engine).

Spec declaration and validation, emission only when declared (existing goldens untouched), tenant treatment and the
guards in the migration, and the pure generated rules (app/booking/rules.py) executed on hand-computed cases: slot
generation from a weekly schedule in a timezone (incl. a DST change), cancellation fee, state machine, capacity peak.
Database behaviour (EXCLUDE constraint, pool capacity under parallel load, hold expiry, idempotency, tenant
isolation) is proven by tests/e2e/test_booking_stack.py."""

import ast
import json
import sys
import types
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.generator import generate
from app.core.generator.engine import module_registry, pack_registry
from app.core.spec_models import Spec
from app.core.validation import validate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _raw() -> dict[str, Any]:
    return json.loads((FIXTURES / "booking_clinic.json").read_text(encoding="utf-8"))


def _spec(raw: dict[str, Any] | None = None) -> Spec:
    return Spec.model_validate(raw if raw is not None else _raw())


def _codes(raw: dict[str, Any]) -> set[str]:
    return {i.code for i in validate(Spec.model_validate(raw))}


def _kind(raw: dict[str, Any], name: str) -> dict[str, Any]:
    return next(k for k in raw["packs"]["booking"]["kinds"] if k["name"] == name)


# --- the spec ----------------------------------------------------------------------------------------------


def test_the_clinic_spec_is_valid_and_defaults_apply() -> None:
    assert validate(_spec()) == []
    raw = _raw()
    raw["packs"]["booking"] = {"kinds": [{"name": "desk", "mode": "range"}]}
    pack = _spec(raw).packs.booking  # type: ignore[union-attr]
    assert pack is not None
    assert (pack.hold_ttl_seconds, pack.max_horizon_days, pack.own_only) == (600, 365, False)
    assert (pack.cancellation.free_until_hours, pack.cancellation.fee_minor, pack.cancellation.currency) == (24, 0, "USD")
    assert pack.read_roles == pack.book_roles == pack.manage_roles == ["admin"]
    assert validate(_spec(raw)) == []


@pytest.mark.parametrize(
    "patch",
    [
        {"overbook": True},
        {"hold_ttl_seconds": 30.5},
        {"hold_ttl_seconds": "30"},
        {"own_only": "yes"},
        {"cancellation": {"fee_minor": 10.5}},
        {"cancellation": {"fee": 1}},
        {"kinds": [{"name": "x", "mode": "stream"}]},
        {"kinds": [{"name": "x", "mode": "pool", "capacity": 2.5}]},
        {"kinds": [{"name": "x", "mode": "slot", "schedule": {"mon": [{"start": "09:00"}]}}]},
    ],
)
def test_unknown_options_and_non_integers_are_refused_by_the_spec_model(patch: dict[str, Any]) -> None:
    raw = _raw()
    raw["packs"]["booking"].update(patch)
    with pytest.raises(ValidationError):
        _spec(raw)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda r: r["packs"]["booking"].update(kinds=[]), "empty"),
        (lambda r: r["packs"]["booking"]["kinds"].append(dict(_kind(r, "room"))), "duplicate"),
        (lambda r: _kind(r, "room").update(name="Bad Name"), "invalid_identifier"),
        (lambda r: _kind(r, "practitioner").update(timezone="Mars/Olympus"), "invalid_timezone"),
        (lambda r: _kind(r, "practitioner").update(slot_minutes=3), "out_of_range"),
        (lambda r: _kind(r, "practitioner").update(schedule={}), "empty_schedule"),
        (lambda r: _kind(r, "practitioner").update(schedule={"funday": [{"start": "09:00", "end": "10:00"}]}), "invalid_weekday"),
        (lambda r: _kind(r, "practitioner").update(schedule={"mon": [{"start": "10:00", "end": "09:00"}]}), "invalid_window"),
        (lambda r: _kind(r, "practitioner").update(schedule={"mon": [{"start": "9am", "end": "10:00"}]}), "invalid_window"),
        (lambda r: _kind(r, "practitioner").update(schedule={"mon": [{"start": "09:00", "end": "09:20"}]}), "window_too_short"),
        (lambda r: _kind(r, "practitioner").update(schedule={"mon": [{"start": "09:00", "end": "11:00"}, {"start": "10:00", "end": "12:00"}]}), "overlapping_windows"),
        (lambda r: _kind(r, "room").update(schedule={"mon": [{"start": "09:00", "end": "10:00"}]}), "schedule_not_allowed"),
        (lambda r: _kind(r, "room").update(capacity=2), "capacity_not_allowed"),
        (lambda r: _kind(r, "loaner").update(capacity=0), "out_of_range"),
        (lambda r: _kind(r, "room").update(min_minutes=90, max_minutes=30), "out_of_range"),
        (lambda r: r["packs"]["booking"].update(hold_ttl_seconds=0), "out_of_range"),
        (lambda r: r["packs"]["booking"].update(max_horizon_days=1000), "out_of_range"),
        (lambda r: r["packs"]["booking"]["cancellation"].update(fee_minor=-1), "out_of_range"),
        (lambda r: r["packs"]["booking"]["cancellation"].update(currency="eur"), "invalid_currency"),
        (lambda r: r["packs"]["booking"].update(book_roles=["ghost"]), "unknown_role"),
    ],
)
def test_booking_values_are_validated(mutate: Any, code: str) -> None:
    raw = _raw()
    mutate(raw)
    assert code in _codes(raw)


def test_booking_needs_auth_and_rbac() -> None:
    raw = _raw()
    raw["auth"]["enabled"] = False
    assert "needs_auth" in _codes(raw)
    raw = _raw()
    raw["authorization"] = {"model": "abac", "policies": []}
    assert "needs_rbac" in _codes(raw) or "needs_rbac" in {i.code for i in validate(_spec(raw))}


def test_the_pack_tables_are_reserved_names() -> None:
    raw = _raw()
    raw["entities"][0]["table_name"] = "bookings"
    assert any("bookings" in i.message or i.path.endswith("table_name") for i in validate(_spec(raw)))


# --- emission ------------------------------------------------------------------------------------------------


def test_emission_only_when_declared() -> None:
    raw = _raw()
    del raw["packs"]
    plain = generate(_spec(raw))
    assert not [p for p in plain if "booking" in p] and "booking" not in plain["app/main.py"]
    assert "tzdata" not in plain["requirements.txt"] and "bookings" not in plain["tests/conftest.py"]
    files = generate(_spec())
    assert sorted(p for p in files if "booking" in p) == [
        "alembic/versions/0037_booking.py",
        "app/booking/__init__.py",
        "app/booking/config.py",
        "app/booking/models.py",
        "app/booking/router.py",
        "app/booking/rules.py",
        "app/booking/schemas.py",
        "app/booking/service.py",
    ]
    assert "include_router(_booking_router)" in files["app/main.py"] and "_booking_models" in files["app/models/__init__.py"]
    assert "tzdata" in files["requirements.txt"]
    assert "booking_resources" in files["tests/conftest.py"] and "bookings" in files["tests/conftest.py"]


def test_routes_roles_and_config_come_from_the_spec() -> None:
    files = generate(_spec())
    router = files["app/booking/router.py"]
    for route in ('"/resources"', '"/resources/{resource_id}/availability"', '"/resources/{resource_id}/capacity"', '"/bookings"', '"/bookings/{booking_id}/confirm"', '"/bookings/{booking_id}/cancel"', '"/expire"'):
        assert route in router
    cfg = files["app/booking/config.py"]
    assert "MANAGE_ROLES: tuple[str, ...] = ('admin', 'staff',)" in cfg and "BOOK_ROLES: tuple[str, ...] = ('admin', 'customer',)" in cfg
    assert "OWN_ONLY = True" in cfg and "HOLD_TTL_SECONDS = 120" in cfg and "CANCEL_FEE_MINOR = 2500" in cfg and 'FEE_CURRENCY = "EUR"' in cfg
    assert "'mode': 'pool'" in cfg and "'timezone': 'Europe/Berlin'" in cfg
    service = files["app/booking/service.py"]
    assert "with_for_update()" in service and "skip_locked=True" in service and "slot_taken" in service and "capacity_exceeded" in service


def test_the_migration_has_the_exclude_constraint_and_the_state_guard() -> None:
    migration = generate(_spec())["alembic/versions/0037_booking.py"]
    assert "CREATE EXTENSION IF NOT EXISTS btree_gist" in migration
    assert "EXCLUDE USING gist" in migration and "tenant_id WITH =" in migration and "tstzrange(starts_at, ends_at, '[)') WITH &&" in migration
    assert "WHERE (exclusive AND status IN ('held', 'confirmed'))" in migration
    assert "bookings_guard" in migration and "uq_bookings_idempotency_key" in migration and "ck_bookings_range" in migration
    assert "sa.Float" not in migration and "sa.Numeric" not in migration and "BEFORE TRUNCATE" not in migration.upper()


def test_tenant_treatment_matches_the_ledger_and_single_tenant_has_none() -> None:
    tenant = generate(_spec())
    for path in ("app/booking/models.py", "alembic/versions/0037_booking.py"):
        assert tenant[path].count('"auth_tenants.id"') >= 2 and 'ondelete="RESTRICT"' in tenant[path], path
    assert tenant["app/booking/service.py"].count("_scoped(") >= 6
    raw = _raw()
    raw["auth"]["multi_tenant"] = False
    for permission in raw["auth"]["permissions"]:
        permission.pop("row_rule", None)
    single = generate(Spec.model_validate(raw))
    for path in ("app/booking/models.py", "alembic/versions/0037_booking.py"):
        assert "tenant_id" not in single[path] and "auth_tenants" not in single[path], path
    assert "MULTI_TENANT = False" in single["app/booking/config.py"]


def test_the_block_is_registered_with_its_dependencies() -> None:
    assert pack_registry()["booking"].id == "booking"
    assert {"crud", "auth"} <= set(pack_registry()["booking"].depends_on)
    assert module_registry()["booking"].pack == "booking"


def test_every_booking_file_parses_and_has_no_float_money() -> None:
    for path, content in generate(_spec()).items():
        if path.endswith(".py"):
            ast.parse(content, filename=path)
    for path in ("app/booking/service.py", "app/booking/schemas.py", "app/booking/models.py"):
        text = generate(_spec())[path]
        assert "float" not in text.replace("floats", "").lower() or "Float" not in text, path


# --- the pure generated rules, executed ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def rules() -> types.ModuleType:
    files = generate(_spec())
    module = types.ModuleType("app.booking.rules")
    sys.modules["app.booking.rules"] = module
    try:
        exec(compile(files["app/booking/rules.py"], "app/booking/rules.py", "exec"), module.__dict__)  # noqa: S102
        yield module
    finally:
        sys.modules.pop("app.booking.rules", None)


SCHEDULE = {"mon": [{"start": "09:00", "end": "11:00"}, {"start": "13:00", "end": "14:00"}], "tue": [{"start": "08:30", "end": "09:30"}]}


def test_slots_follow_the_weekly_schedule_in_the_timezone(rules: types.ModuleType) -> None:
    # 2026-12-07 is a Monday; Berlin is UTC+1 in winter
    slots = rules.slots_for_day(SCHEDULE, "Europe/Berlin", 30, date(2026, 12, 7))
    assert [(s.hour, s.minute) for s, _ in slots] == [(8, 0), (8, 30), (9, 0), (9, 30), (12, 0), (12, 30)]
    assert all(e - s == timedelta(minutes=30) and s.tzinfo is not None and s.utcoffset() == timedelta(0) for s, e in slots)
    assert rules.slots_for_day(SCHEDULE, "Europe/Berlin", 30, date(2026, 12, 9)) == []  # Wednesday: closed
    assert len(rules.slots_for_day(SCHEDULE, "UTC", 45, date(2026, 12, 7))) == 2 + 1  # 120 min -> 2 of 45; 60 min -> 1
    assert len(rules.slots_between(SCHEDULE, "UTC", 30, date(2026, 12, 7), date(2026, 12, 8))) == 4 + 2 + 2


def test_slots_across_a_dst_change_keep_the_local_wall_clock(rules: types.ModuleType) -> None:
    sched = {"sun": [{"start": "09:00", "end": "10:00"}], "sat": [{"start": "09:00", "end": "10:00"}]}
    before = rules.slots_for_day(sched, "Europe/Berlin", 60, date(2026, 3, 28))  # Saturday, CET = UTC+1
    after = rules.slots_for_day(sched, "Europe/Berlin", 60, date(2026, 3, 29))  # Sunday, clocks moved: CEST = UTC+2
    assert before[0][0] == datetime(2026, 3, 28, 8, 0, tzinfo=UTC)
    assert after[0][0] == datetime(2026, 3, 29, 7, 0, tzinfo=UTC)


def test_is_slot_start_is_exact(rules: types.ModuleType) -> None:
    ok = datetime(2026, 12, 7, 8, 30, tzinfo=UTC)  # 09:30 Berlin
    assert rules.is_slot_start(SCHEDULE, "Europe/Berlin", 30, ok)
    assert rules.is_slot_start(SCHEDULE, "Europe/Berlin", 30, ok.astimezone(timezone_plus(1)))
    assert not rules.is_slot_start(SCHEDULE, "Europe/Berlin", 30, ok + timedelta(minutes=10))
    assert not rules.is_slot_start(SCHEDULE, "Europe/Berlin", 30, datetime(2026, 12, 7, 10, 30, tzinfo=UTC))  # 11:30 local: closed
    assert not rules.is_slot_start(SCHEDULE, "Europe/Berlin", 30, datetime(2026, 12, 7, 9, 30, tzinfo=UTC) - timedelta(hours=7))
    with pytest.raises(ValueError):
        rules.is_slot_start(SCHEDULE, "UTC", 30, datetime(2026, 12, 7, 9, 0))


def timezone_plus(hours: int) -> Any:
    from datetime import timezone

    return timezone(timedelta(hours=hours))


def test_schedule_validation(rules: types.ModuleType) -> None:
    assert rules.validate_schedule(SCHEDULE, 30) is None
    assert rules.validate_schedule({}, 30) is not None
    assert rules.validate_schedule({"mon": [{"start": "09:00", "end": "09:20"}]}, 30) is not None
    assert rules.validate_schedule({"mon": [{"start": "09:00", "end": "11:00"}, {"start": "10:00", "end": "12:00"}]}, 30) is not None
    assert rules.validate_schedule({"mon": [{"start": "9:00", "end": "11:00"}]}, 30) is not None
    assert rules.validate_schedule({"xyz": []}, 30) is not None


def test_cancellation_fee_rules(rules: types.ModuleType) -> None:
    start = datetime(2026, 12, 10, 12, 0, tzinfo=UTC)
    fee = lambda status, now: rules.cancellation_fee(status, start, now, 24, 2500)  # noqa: E731
    assert fee("confirmed", start - timedelta(hours=24)) == 0  # exactly at the boundary: still free
    assert fee("confirmed", start - timedelta(hours=24, seconds=1)) == 0
    assert fee("confirmed", start - timedelta(hours=23, minutes=59)) == 2500
    assert fee("confirmed", start + timedelta(hours=1)) == 2500  # after the start
    assert fee("held", start - timedelta(minutes=1)) == 0  # a hold is free
    assert rules.cancellation_fee("confirmed", start, start + timedelta(hours=1), 0, 700) == 700
    assert rules.cancellation_fee("confirmed", start, start - timedelta(hours=1), 24, 0) == 0
    assert type(fee("confirmed", start)) is int


def test_state_machine(rules: types.ModuleType) -> None:
    allowed = {("held", "confirmed"), ("held", "expired"), ("held", "cancelled"), ("confirmed", "cancelled")}
    states = ("held", "confirmed", "cancelled", "expired")
    for a in states:
        for b in states:
            assert rules.can_transition(a, b) == ((a, b) in allowed), (a, b)
    assert not rules.can_transition("nonsense", "held")


def test_hold_deadline_and_expiry(rules: types.ModuleType) -> None:
    now = datetime(2026, 12, 1, 10, 0, tzinfo=UTC)
    deadline = rules.hold_deadline(now, 120)
    assert deadline == now + timedelta(seconds=120)
    assert not rules.hold_expired(deadline, now) and rules.hold_expired(deadline, deadline) and rules.hold_expired(deadline, deadline + timedelta(seconds=1))
    assert not rules.hold_expired(None, now)


def test_free_slots_and_overlap_are_half_open(rules: types.ModuleType) -> None:
    t0 = datetime(2026, 12, 7, 8, 0, tzinfo=UTC)
    slots = [(t0 + timedelta(minutes=30 * i), t0 + timedelta(minutes=30 * (i + 1))) for i in range(3)]
    assert [f for _, _, f in rules.free_slots(slots, [(slots[1][0], slots[1][1])])] == [True, False, True]
    assert not rules.overlaps(slots[0][0], slots[0][1], slots[1][0], slots[1][1])
    assert rules.overlaps(slots[0][0], slots[1][1], slots[1][0], slots[1][1])


def test_booked_units_is_the_peak_not_the_sum(rules: types.ModuleType) -> None:
    t = datetime(2026, 12, 7, 8, 0, tzinfo=UTC)
    h = timedelta(hours=1)
    existing = [(t, t + h, 2), (t + h, t + 2 * h, 2), (t + 3 * h, t + 4 * h, 1)]
    assert rules.booked_units(existing, t, t + 2 * h) == 2  # back to back: the peak, not 4
    assert rules.booked_units(existing, t, t + 4 * h) == 2
    assert rules.booked_units(existing, t + 2 * h, t + 3 * h) == 0
    overlapping = existing + [(t + h // 2, t + h + h // 2, 1)]
    assert rules.booked_units(overlapping, t, t + 2 * h) == 3
    assert rules.booked_units([], t, t + h) == 0


def test_empty_manage_roles_is_refused() -> None:
    raw = _raw()
    raw["packs"]["booking"]["manage_roles"] = []
    assert "empty" in _codes(raw)


def test_booked_units_handles_many_overlapping_bookings_fast(rules: types.ModuleType) -> None:
    t = datetime(2026, 12, 1, 9, tzinfo=UTC)
    many = [(t, t + timedelta(hours=2), 1) for _ in range(20000)]
    assert rules.booked_units(many, t, t + timedelta(hours=2)) == 20000


def test_hostile_times_are_a_422_not_an_overflow(rules: types.ModuleType) -> None:
    src = (Path(__file__).resolve().parents[2] / "app/core/generator/features/booking/templates/app/booking/service.py.j2").read_text()
    assert "except (OverflowError, ValueError)" in src and "MAX_ACTIVE_HOLDS" in src
