"""Pure booking rules (generated). No database, no clock: every function takes the time it needs. Integers and
timezone-aware datetimes only.

* Slots: a weekly schedule (`mon`..`sun`, windows of local wall-clock `HH:MM`) in an IANA timezone becomes
  fixed-length slots, converted to UTC. Slots are `[start, end)`; a slot must fit inside its window.
* States: held -> confirmed | expired | cancelled; confirmed -> cancelled. cancelled and expired are final.
* Cancellation fee: free until `free_until_hours` before the start, then a flat integer `fee_minor`.
"""

import re
from bisect import bisect_left
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
ACTIVE = ("held", "confirmed")
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "held": ("confirmed", "expired", "cancelled"),
    "confirmed": ("cancelled",),
    "cancelled": (),
    "expired": (),
}
_HHMM = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")

Schedule = dict[str, list[dict[str, str]]]


def can_transition(current: str, new: str) -> bool:
    return new in TRANSITIONS.get(current, ())


def minutes_of(value: str) -> int | None:
    match = _HHMM.fullmatch(value) if isinstance(value, str) else None
    return int(match.group(1)) * 60 + int(match.group(2)) if match else None


def validate_schedule(schedule: object, slot_minutes: int) -> str | None:
    """None when the schedule is usable, otherwise a short reason."""
    if not isinstance(schedule, dict) or not schedule:
        return "the schedule needs at least one weekday"
    for day, windows in schedule.items():
        if day not in WEEKDAYS:
            return "weekday keys are mon, tue, wed, thu, fri, sat, sun"
        if not isinstance(windows, list):
            return f"{day}: a list of windows is expected"
        spans: list[tuple[int, int]] = []
        for window in windows:
            a = minutes_of(window.get("start", "")) if isinstance(window, dict) else None
            b = minutes_of(window.get("end", "")) if isinstance(window, dict) else None
            if a is None or b is None or a >= b:
                return f"{day}: windows need start and end as HH:MM with start before end"
            if b - a < slot_minutes:
                return f"{day}: a window must fit at least one slot"
            spans.append((a, b))
        spans.sort()
        if any(spans[i][1] > spans[i + 1][0] for i in range(len(spans) - 1)):
            return f"{day}: windows must not overlap"
    return None


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("a timezone-aware datetime is required")
    return value.astimezone(UTC)


def slots_for_day(schedule: Schedule, tz_name: str, slot_minutes: int, day: date) -> list[tuple[datetime, datetime]]:
    """The slots of one LOCAL calendar day, as UTC `(start, end)` pairs in time order."""
    tz = ZoneInfo(tz_name)
    out: list[tuple[datetime, datetime]] = []
    step = timedelta(minutes=slot_minutes)
    for window in sorted(schedule.get(WEEKDAYS[day.weekday()], []), key=lambda w: w["start"]):
        a, b = minutes_of(window["start"]), minutes_of(window["end"])
        if a is None or b is None:
            continue
        start = datetime.combine(day, time(a // 60, a % 60), tzinfo=tz).astimezone(UTC)
        end = datetime.combine(day, time(b // 60, b % 60), tzinfo=tz).astimezone(UTC)
        while start + step <= end:
            out.append((start, start + step))
            start += step
    return sorted(out)


def slots_between(
    schedule: Schedule, tz_name: str, slot_minutes: int, first_day: date, last_day: date
) -> list[tuple[datetime, datetime]]:
    """Slots of every local day from `first_day` to `last_day` inclusive."""
    out: list[tuple[datetime, datetime]] = []
    day = first_day
    while day <= last_day:
        out.extend(slots_for_day(schedule, tz_name, slot_minutes, day))
        day += timedelta(days=1)
    return out


def is_slot_start(schedule: Schedule, tz_name: str, slot_minutes: int, starts_at: datetime) -> bool:
    """True when `starts_at` is exactly the start of a slot of the schedule."""
    start = _aware(starts_at)
    local_day = start.astimezone(ZoneInfo(tz_name)).date()
    for day in (local_day - timedelta(days=1), local_day, local_day + timedelta(days=1)):
        if any(s == start for s, _ in slots_for_day(schedule, tz_name, slot_minutes, day)):
            return True
    return False


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Half-open intervals: back-to-back ranges do not overlap."""
    return a_start < b_end and b_start < a_end


def free_slots(
    slots: list[tuple[datetime, datetime]], busy: list[tuple[datetime, datetime]]
) -> list[tuple[datetime, datetime, bool]]:
    """Every slot with a `free` flag: free when it overlaps no busy interval."""
    # O(n log n): busy sorted by start, with a running maximum of the ends; a slot is taken when some interval
    # starting before the slot's end also ends after the slot's start
    ordered = sorted(busy)
    starts = [bs for bs, _ in ordered]
    reach: list[datetime] = []
    for _, be in ordered:
        reach.append(be if not reach or be > reach[-1] else reach[-1])
    out: list[tuple[datetime, datetime, bool]] = []
    for s, e in slots:
        n = bisect_left(starts, e)  # intervals with start < e
        out.append((s, e, not (n and reach[n - 1] > s)))
    return out


def booked_units(bookings: list[tuple[datetime, datetime, int]], start: datetime, end: datetime) -> int:
    """The most units in use at any instant of `[start, end)` (a sorted sweep over the booking edges, O(n log n))."""
    events: list[tuple[datetime, int]] = []
    for b_start, b_end, q in bookings:
        if overlaps(b_start, b_end, start, end):
            events.append((max(b_start, start), q))
            events.append((min(b_end, end), -q))
    events.sort(key=lambda e: (e[0], e[1]))  # at one instant, releases (negative) come before takes
    peak = current = 0
    for _, delta in events:
        current += delta
        peak = max(peak, current)
    return peak


def cancellation_fee(status: str, starts_at: datetime, now: datetime, free_until_hours: int, fee_minor: int) -> int:
    """0 for a hold or a cancellation at least `free_until_hours` before the start, else `fee_minor`."""
    if status != "confirmed":
        return 0
    if _aware(now) <= _aware(starts_at) - timedelta(hours=free_until_hours):
        return 0
    return fee_minor


def can_cancel_now(status: str, starts_at: datetime, now: datetime) -> bool:
    """A confirmed booking that has started (or passed) is history: only a hold or a future booking can be cancelled."""
    return status != "confirmed" or _aware(starts_at) > _aware(now)


def hold_deadline(now: datetime, ttl_seconds: int) -> datetime:
    return _aware(now) + timedelta(seconds=ttl_seconds)


def hold_expired(hold_expires_at: datetime | None, now: datetime) -> bool:
    return hold_expires_at is not None and _aware(hold_expires_at) <= _aware(now)
