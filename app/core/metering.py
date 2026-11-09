"""Usage metering registry (B4-5, C23): which builder-side metrics exist and how they reset.

Pure: no database, no clock of its own. This meters the BUILDER's usage per organization (imports,
workspaces, previews), not what generated apps do. A limit of None means unlimited.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

Period = Literal["month", "day", "none"]  # none = a gauge: it never resets, it goes up and down
GAUGE_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)  # the single period_start of every gauge


@dataclass(frozen=True)
class MetricDef:
    unit: str
    default_limit: int | None
    period: Period


METRICS: dict[str, MetricDef] = {
    "imports.rows": MetricDef("rows", 50_000, "month"),
    "imports.batches": MetricDef("batches", 50, "day"),
    "workspaces.active": MetricDef("workspaces", 5, "none"),
    "previews.started": MetricDef("previews", 20, "day"),
}


def known(metric: str) -> bool:
    return metric in METRICS


def period_bounds(now: datetime, period: Period) -> tuple[datetime, datetime | None]:
    """[start, end) of the period holding `now`, in UTC. A gauge has the fixed epoch start, no end."""
    if now.tzinfo is None:
        raise ValueError("period_bounds needs a timezone-aware datetime")
    now = now.astimezone(UTC)
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)
    if period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return start, nxt
    return GAUGE_EPOCH, None


def resolve_limit(metric: str, override: tuple[bool, int | None]) -> int | None:
    """override = (has_override_row, limit_value). An override row wins, even when it is None
    (explicitly unlimited); with no row the registry default applies."""
    has_row, value = override
    return value if has_row else METRICS[metric].default_limit
