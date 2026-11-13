"""Validation for `packs.booking` (Cycle 5, D12 reservation engine). Structure (unknown options, floats where an
integer is required) is refused by the spec models (extra=forbid, StrictInt); this module checks the values and the
cross-section rules. Issues go through `add(path, code, message)`. Nothing here runs anything."""

import re
from collections.abc import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.spec_models import Spec, SpecBookingKind

Add = Callable[[str, str, str], None]

BOOKING_TABLES = ("booking_resources", "bookings")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MAX_KINDS = 20
MAX_CAPACITY = 100_000
MAX_FEE_MINOR = 2**53 - 1
_KIND_NAME = re.compile(r"[a-z][a-z0-9_]{0,39}")
_HHMM = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")
_CURRENCY = re.compile(r"[A-Z]{3}")


def booking_active(spec: Spec) -> bool:
    return spec.packs is not None and spec.packs.booking is not None


def booking_tables(spec: Spec) -> tuple[str, ...]:
    return BOOKING_TABLES if booking_active(spec) else ()


def minutes_of(value: str) -> int | None:
    """`HH:MM` -> minutes since midnight, None when it is not a valid wall-clock time."""
    match = _HHMM.fullmatch(value)
    return int(match.group(1)) * 60 + int(match.group(2)) if match else None


def check_booking(spec: Spec, add: Add) -> None:
    if not booking_active(spec):
        return
    pack = spec.packs.booking  # type: ignore[union-attr]
    assert pack is not None
    p = "packs.booking"
    if spec.auth is None or not spec.auth.enabled:
        add(p, "needs_auth", "booking needs auth.enabled: every route needs a signed-in caller")
    elif spec.authorization is not None and spec.authorization.model != "rbac":
        add(p, "needs_rbac", "booking needs authorization.model rbac (it checks roles, not abac / pbac policies)")
    if spec.auth is not None:
        known = {r.name for r in spec.auth.roles}
        for field in ("read_roles", "book_roles", "manage_roles"):
            for role in getattr(pack, field):
                if role not in known:
                    add(f"{p}.{field}", "unknown_role", f"role {role!r} is not an auth role")
    if not pack.manage_roles:
        add(f"{p}.manage_roles", "empty", "manage_roles needs at least one role (an empty list would make nobody a manager)")
    if not pack.kinds:
        add(f"{p}.kinds", "empty", "declare at least one resource kind")
    if len(pack.kinds) > MAX_KINDS:
        add(f"{p}.kinds", "too_many", f"at most {MAX_KINDS} resource kinds")
    names = [k.name for k in pack.kinds]
    if len(set(names)) != len(names):
        add(f"{p}.kinds", "duplicate", "a resource kind is declared twice")
    for i, kind in enumerate(pack.kinds):
        _check_kind(kind, f"{p}.kinds[{i}]", add)
    if not 1 <= pack.hold_ttl_seconds <= 86_400:
        add(f"{p}.hold_ttl_seconds", "out_of_range", "1 .. 86400 seconds")
    if not 1 <= pack.max_horizon_days <= 730:
        add(f"{p}.max_horizon_days", "out_of_range", "1 .. 730 days")
    c = pack.cancellation
    if not 0 <= c.free_until_hours <= 8760:
        add(f"{p}.cancellation.free_until_hours", "out_of_range", "0 .. 8760 hours")
    if not 0 <= c.fee_minor <= MAX_FEE_MINOR:
        add(f"{p}.cancellation.fee_minor", "out_of_range", "0 .. 2**53-1 minor units")
    if not _CURRENCY.fullmatch(c.currency):
        add(f"{p}.cancellation.currency", "invalid_currency", "a 3 letter upper case ISO 4217 code")


def check_schedule(
    schedule: dict[str, list[tuple[str, str]]], p: str, add: Add, slot_minutes: int | None = None
) -> None:
    """Shared with the generated runtime rules: weekday keys mon..sun, valid HH:MM, start < end, no overlap."""
    if not schedule:
        add(p, "empty_schedule", "a slot resource needs at least one opening window")
    for day, windows in schedule.items():
        if day not in WEEKDAYS:
            add(f"{p}.{day[:20]}", "invalid_weekday", "weekday keys are mon, tue, wed, thu, fri, sat, sun")
            continue
        spans: list[tuple[int, int]] = []
        for j, (start, end) in enumerate(windows):
            a, b = minutes_of(start), minutes_of(end)
            if a is None or b is None or a >= b:
                add(f"{p}.{day}[{j}]", "invalid_window", "start and end are HH:MM (24 h) and start is before end")
                continue
            if slot_minutes is not None and b - a < slot_minutes:
                add(f"{p}.{day}[{j}]", "window_too_short", "a window must fit at least one slot")
            spans.append((a, b))
        spans.sort()
        if any(spans[k][1] > spans[k + 1][0] for k in range(len(spans) - 1)):
            add(f"{p}.{day}", "overlapping_windows", "the windows of a day must not overlap")


def _check_kind(kind: SpecBookingKind, p: str, add: Add) -> None:
    if not _KIND_NAME.fullmatch(kind.name):
        add(f"{p}.name", "invalid_identifier", "a kind name is lower case letters, digits and _")
    try:
        ZoneInfo(kind.timezone)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        add(f"{p}.timezone", "invalid_timezone", f"{kind.timezone[:40]!r} is not an IANA timezone")
    if not 1 <= kind.capacity <= MAX_CAPACITY:
        add(f"{p}.capacity", "out_of_range", f"1 .. {MAX_CAPACITY}")
    if kind.mode != "pool" and kind.capacity != 1:
        add(f"{p}.capacity", "capacity_not_allowed", "only a pool has a capacity; slot and range resources hold one booking at a time")
    if kind.mode == "slot":
        if not 5 <= kind.slot_minutes <= 1440:
            add(f"{p}.slot_minutes", "out_of_range", "5 .. 1440 minutes")
        check_schedule(
            {d: [(w.start, w.end) for w in ws] for d, ws in kind.schedule.items()},
            f"{p}.schedule",
            add,
            kind.slot_minutes if 5 <= kind.slot_minutes <= 1440 else None,
        )
    elif kind.schedule:
        add(f"{p}.schedule", "schedule_not_allowed", "only a slot kind has a weekly schedule")
    if kind.mode != "slot":
        if not 1 <= kind.min_minutes <= kind.max_minutes <= 525_600:
            add(f"{p}.min_minutes", "out_of_range", "1 <= min_minutes <= max_minutes <= 525600")
