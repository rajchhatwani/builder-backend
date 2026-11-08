"""The strict 5-field cron shared by the builder's validation and the generated app."""

import datetime as dt

import pytest

from app.core import jobs_cron as cron

UTC = dt.UTC


@pytest.mark.parametrize(
    "expression",
    ["* * * * *", "0 6 * * 1", "*/15 * * * *", "0 0 1 1 *", "5,10,15 8-17 * * 1-5", "0-30/10 0 29 2 *", "0 0 * * 0", "59 23 31 12 6"],
)
def test_valid_expressions(expression: str) -> None:
    cron.validate(expression, "UTC")


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "* * * *",
        "* * * * * *",
        "60 * * * *",
        "-1 * * * *",
        "* 24 * * *",
        "* * 0 * *",
        "* * 32 * *",
        "* * * 0 *",
        "* * * 13 *",
        "* * * * 7",
        "*/0 * * * *",
        "*/61 * * * *",
        "5-2 * * * *",
        "1/5 * * * *",
        "a * * * *",
        "MON * * * *",
        "* * * JAN *",
        "@daily",
        "? * * * *",
        "1,,2 * * * *",
        "1- * * * *",
        "0 0 31 2 *",
        "0 0 30 2 *",
    ],
)
def test_invalid_expressions_are_refused(expression: str) -> None:
    with pytest.raises(cron.CronError):
        cron.validate(expression, "UTC")


def test_unknown_timezones_are_refused() -> None:
    for name in ("Mars/Base", "", "../etc/passwd"):
        with pytest.raises(cron.CronError):
            cron.validate("* * * * *", name)


def at(*args: int) -> dt.datetime:
    return dt.datetime(*args, tzinfo=UTC)


def test_previous_and_next_fire_for_a_weekly_schedule() -> None:
    spec, tz = cron.parse("0 6 * * 1"), cron.zone("UTC")  # Mondays 06:00
    wednesday = at(2026, 11, 4, 12, 0)
    assert cron.previous_fire(spec, tz, wednesday) == at(2026, 11, 2, 6, 0)
    assert cron.next_fire(spec, tz, wednesday) == at(2026, 11, 9, 6, 0)
    assert cron.previous_fire(spec, tz, at(2026, 11, 2, 6, 0)) == at(2026, 11, 2, 6, 0)  # at the tick counts
    assert cron.next_fire(spec, tz, at(2026, 11, 2, 6, 0)) == at(2026, 11, 9, 6, 0)  # strictly after


def test_a_timezone_moves_the_tick() -> None:
    spec, tz = cron.parse("0 6 * * 1"), cron.zone("Asia/Kolkata")  # UTC+5:30, no DST
    assert cron.next_fire(spec, tz, at(2026, 11, 4)) == at(2026, 11, 9, 0, 30)


def test_day_of_month_or_day_of_week_when_both_are_given() -> None:
    spec, tz = cron.parse("0 0 13 * 5"), cron.zone("UTC")  # the 13th OR any Friday
    ticks = []
    moment = at(2026, 11, 1)
    for _ in range(4):
        moment = cron.next_fire(spec, tz, moment) or moment
        ticks.append(moment.day)
    assert ticks == [6, 13, 20, 27]


def test_a_nonexistent_local_time_is_skipped_and_an_ambiguous_one_fires_once() -> None:
    tz = cron.zone("America/New_York")
    spec = cron.parse("30 2 * * *")  # 02:30 does not exist on 2026-03-08, happens once otherwise
    spring = cron.next_fire(spec, tz, at(2026, 3, 8, 0, 0))
    assert spring == dt.datetime(2026, 3, 9, 2, 30, tzinfo=tz).astimezone(UTC)
    autumn_spec = cron.parse("30 1 * * *")  # 01:30 happens twice on 2026-11-01
    first = cron.next_fire(autumn_spec, tz, at(2026, 11, 1, 0, 0))
    assert first == at(2026, 11, 1, 5, 30)  # the first occurrence (EDT)
    assert cron.next_fire(autumn_spec, tz, first) == at(2026, 11, 2, 6, 30)  # not again an hour later


def test_naive_datetimes_are_refused() -> None:
    spec, tz = cron.parse("* * * * *"), cron.zone("UTC")
    with pytest.raises(cron.CronError):
        cron.previous_fire(spec, tz, dt.datetime(2026, 1, 1))
    with pytest.raises(cron.CronError):
        cron.next_fire(spec, tz, dt.datetime(2026, 1, 1))


def test_leap_day_schedules_are_found() -> None:
    spec, tz = cron.parse("0 0 29 2 *"), cron.zone("UTC")
    assert cron.next_fire(spec, tz, at(2026, 3, 1)) == at(2028, 2, 29, 0, 0)
