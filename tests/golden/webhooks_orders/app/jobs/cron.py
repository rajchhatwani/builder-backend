"""Strict 5-field cron (minute hour day-of-month month day-of-week), timezone-aware.

One source for two users: the builder validates a spec's schedules with it, and the generator copies this
very file into a generated project as `app/jobs/cron.py`, so the builder and the running app can never
disagree about what an expression means. Standard library only; keep it that way.

Accepted per field: `*`, a number, `a-b`, `a-b/n`, `*/n`, and comma lists of those. Rejected: names
(MON, JAN), `?`, `L`, `W`, `#`, a sixth (seconds) field, `@daily`-style macros, anything out of range.
Day-of-week is 0-6 with 0 = Sunday (7 is refused). When both day-of-month and day-of-week are restricted
a day matches if EITHER does (the classic cron rule).

Local times that do not exist (the spring-forward gap) are skipped; a local time that happens twice (the
autumn fold) fires once, at its first occurrence.
"""

import datetime as _dt
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_FIELDS = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day of month", 1, 31),
    ("month", 1, 12),
    ("day of week", 0, 6),
)
_NUMBER = re.compile(r"[0-9]{1,2}")
_HORIZON_DAYS = 366 * 9  # far enough for 29 February schedules, near enough to stay cheap


class CronError(ValueError):
    """The expression or timezone is not acceptable."""


@dataclass(frozen=True)
class CronSpec:
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    days_restricted: bool
    weekdays_restricted: bool


def _number(text: str, label: str, low: int, high: int) -> int:
    if not _NUMBER.fullmatch(text):
        raise CronError(f"{label}: {text!r} is not a number")
    value = int(text)
    if not low <= value <= high:
        raise CronError(f"{label}: {value} is outside {low}-{high}")
    return value


def _field(text: str, label: str, low: int, high: int) -> frozenset[int]:
    if text == "":
        raise CronError(f"{label}: empty")
    out: set[int] = set()
    for part in text.split(","):
        if part == "":
            raise CronError(f"{label}: empty list item")
        body, slash, step_text = part.partition("/")
        step = 1
        if slash:
            step = _number(step_text, label, 1, high - low + 1)
        if body == "*":
            start, end = low, high
        elif "-" in body:
            first, _, last = body.partition("-")
            start, end = _number(first, label, low, high), _number(last, label, low, high)
            if start > end:
                raise CronError(f"{label}: range {body!r} runs backwards")
        else:
            if slash:
                raise CronError(f"{label}: a step needs * or a range, not {body!r}")
            start = end = _number(body, label, low, high)
        out.update(range(start, end + 1, step))
    return frozenset(out)


def parse(expression: str) -> CronSpec:
    """Parse a 5-field expression; raises CronError (never returns something half-valid)."""
    if not isinstance(expression, str):
        raise CronError("a cron expression is text")
    parts = expression.split()
    if len(parts) != 5:
        raise CronError(f"needs exactly 5 fields (minute hour day-of-month month day-of-week), got {len(parts)}")
    sets = [_field(text, label, low, high) for text, (label, low, high) in zip(parts, _FIELDS, strict=True)]
    return CronSpec(
        minutes=sets[0],
        hours=sets[1],
        days=sets[2],
        months=sets[3],
        weekdays=sets[4],
        days_restricted=parts[2] != "*",
        weekdays_restricted=parts[4] != "*",
    )


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise CronError(f"unknown timezone {name!r}") from None


def _day_matches(spec: CronSpec, day: _dt.date) -> bool:
    if day.month not in spec.months:
        return False
    dom = day.day in spec.days
    dow = (day.weekday() + 1) % 7 in spec.weekdays  # Monday=0 in Python; cron's Sunday is 0
    if spec.days_restricted and spec.weekdays_restricted:
        return dom or dow
    return dom and dow


def _exists_once(local: _dt.datetime, tz: ZoneInfo) -> _dt.datetime | None:
    """The UTC instant of a naive local time, or None when it does not exist in `tz`."""
    first = local.replace(tzinfo=tz, fold=0)
    utc = first.astimezone(_dt.UTC)
    if utc.astimezone(tz).replace(tzinfo=None) != local:
        return None  # inside the gap: the clock never showed this time
    return utc


def _times(spec: CronSpec) -> list[_dt.time]:
    return [_dt.time(h, m) for h in sorted(spec.hours) for m in sorted(spec.minutes)]


def previous_fire(spec: CronSpec, tz: ZoneInfo, now: _dt.datetime) -> _dt.datetime | None:
    """The latest fire time at or before `now` (UTC, aware), or None within the search horizon."""
    if now.tzinfo is None:
        raise CronError("now must be timezone-aware")
    local_now = now.astimezone(tz)
    times = _times(spec)
    day = local_now.date()
    for _ in range(_HORIZON_DAYS):
        if _day_matches(spec, day):
            for t in reversed(times):
                utc = _exists_once(_dt.datetime.combine(day, t), tz)
                if utc is not None and utc <= now:
                    return utc
        day -= _dt.timedelta(days=1)
    return None


def next_fire(spec: CronSpec, tz: ZoneInfo, after: _dt.datetime) -> _dt.datetime | None:
    """The first fire time strictly after `after` (UTC, aware), or None within the search horizon."""
    if after.tzinfo is None:
        raise CronError("after must be timezone-aware")
    day = after.astimezone(tz).date()
    times = _times(spec)
    for _ in range(_HORIZON_DAYS):
        if _day_matches(spec, day):
            for t in times:
                utc = _exists_once(_dt.datetime.combine(day, t), tz)
                if utc is not None and utc > after:
                    return utc
        day += _dt.timedelta(days=1)
    return None


def validate(expression: str, timezone: str) -> None:
    """Raise CronError unless the expression parses, the zone exists and the schedule can ever fire."""
    spec = parse(expression)
    tz = zone(timezone)
    if next_fire(spec, tz, _dt.datetime(2024, 1, 1, tzinfo=_dt.UTC)) is None:
        raise CronError("this schedule never fires (for example 31 February)")
