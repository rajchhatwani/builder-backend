"""B4-5: the pure metering registry: period bounds, limit resolution."""

from datetime import UTC, datetime

import pytest

from app.core import metering


def test_registry_has_the_metrics() -> None:
    assert set(metering.METRICS) == {
        "imports.rows", "imports.batches", "workspaces.active", "previews.started", "reports.runs",
    }  # fmt: skip
    assert metering.METRICS["imports.rows"].period == "month"
    assert metering.METRICS["imports.rows"].default_limit == 50_000
    assert metering.METRICS["imports.batches"].period == "day"
    assert metering.METRICS["workspaces.active"].period == "none"
    assert metering.METRICS["previews.started"].default_limit == 20
    assert metering.known("imports.rows") and not metering.known("api.requests")


def test_day_and_month_bounds_in_utc() -> None:
    now = datetime(2026, 11, 9, 13, 5, 7, 99, tzinfo=UTC)
    assert metering.period_bounds(now, "day") == (
        datetime(2026, 11, 9, tzinfo=UTC), datetime(2026, 11, 10, tzinfo=UTC),
    )  # fmt: skip
    assert metering.period_bounds(now, "month") == (
        datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 12, 1, tzinfo=UTC),
    )  # fmt: skip


def test_month_rolls_over_the_year_and_handles_february() -> None:
    dec = datetime(2026, 12, 31, 23, 59, tzinfo=UTC)
    assert metering.period_bounds(dec, "month")[1] == datetime(2027, 1, 1, tzinfo=UTC)
    feb = datetime(2028, 2, 29, 12, tzinfo=UTC)
    assert metering.period_bounds(feb, "month") == (
        datetime(2028, 2, 1, tzinfo=UTC), datetime(2028, 3, 1, tzinfo=UTC),
    )  # fmt: skip


def test_bounds_convert_other_timezones_to_utc() -> None:
    from datetime import timedelta, timezone

    late = datetime(2026, 11, 9, 23, 30, tzinfo=timezone(timedelta(hours=-5)))  # 04:30 UTC next day
    assert metering.period_bounds(late, "day")[0] == datetime(2026, 11, 10, tzinfo=UTC)


def test_gauge_has_a_fixed_start_and_no_end() -> None:
    now = datetime(2026, 11, 9, tzinfo=UTC)
    assert metering.period_bounds(now, "none") == (metering.GAUGE_EPOCH, None)


def test_naive_datetime_is_refused() -> None:
    with pytest.raises(ValueError):
        metering.period_bounds(datetime(2026, 1, 1), "day")


def test_limit_resolution_override_beats_default_and_none_is_unlimited() -> None:
    assert metering.resolve_limit("imports.rows", (False, None)) == 50_000
    assert metering.resolve_limit("imports.rows", (True, 10)) == 10
    assert metering.resolve_limit("imports.rows", (True, None)) is None  # explicitly unlimited
