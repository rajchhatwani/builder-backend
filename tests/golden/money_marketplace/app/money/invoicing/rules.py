"""Invoice rules (generated). Pure functions: no database, no clock, no float. Imported by the service and
exercised on their own by the unit tests.

State machine:  draft -> issued -> partially_paid -> paid;  draft | issued -> void.
Aging: an invoice is `current` while it is not past its due date; otherwise it falls into the bucket of its
days past due, e.g. bounds (30, 60, 90) give 1-30, 31-60, 61-90 and 91+. All sums are integer minor units."""

from collections.abc import Iterable
from datetime import date

TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"issued", "void"}),
    "issued": frozenset({"partially_paid", "paid", "void"}),
    "partially_paid": frozenset({"partially_paid", "paid"}),
    "paid": frozenset(),
    "void": frozenset(),
}
STATUSES = tuple(TRANSITIONS)


def can_transition(old: str, new: str) -> bool:
    return new in TRANSITIONS.get(old, frozenset())


def invoice_number(prefix: str, kind: str, sequence: int) -> str:
    """INV-000042 for a receivable, INV-AP-000042 for a payable bill."""
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise ValueError("sequence must be a positive int")
    return f"{prefix}{'AP-' if kind == 'payable' else ''}{sequence:06d}"


def days_past_due(due: date, as_of: date) -> int:
    """Whole days after the due date (<= 0 means not yet due)."""
    return (as_of - due).days


def bucket_labels(bounds: Iterable[int]) -> list[str]:
    ordered = list(bounds)
    labels = []
    low = 1
    for bound in ordered:
        labels.append(f"{low}-{bound}")
        low = bound + 1
    labels.append(f"{low}+")
    return labels


def bucket_index(days: int, bounds: Iterable[int]) -> int | None:
    """None while current (days <= 0); otherwise the index into bucket_labels(bounds)."""
    ordered = list(bounds)
    if days <= 0:
        return None
    for index, bound in enumerate(ordered):
        if days <= bound:
            return index
    return len(ordered)


def age(rows: Iterable[tuple[str, date, int, int]], as_of: date, bounds: Iterable[int]) -> list[dict[str, object]]:
    """rows = (currency, due_date, outstanding_minor, invoice_count). One entry per currency, sorted by code."""
    ordered = list(bounds)
    labels = bucket_labels(ordered)
    lows = [1, *[b + 1 for b in ordered]]
    highs: list[int | None] = [*ordered, None]
    by_currency: dict[str, dict[str, object]] = {}
    for currency, due, outstanding, count in rows:
        entry = by_currency.setdefault(
            currency,
            {
                "currency": currency,
                "current_minor": 0,
                "current_count": 0,
                "buckets": [
                    {"label": labels[i], "from_days": lows[i], "to_days": highs[i], "amount_minor": 0, "count": 0}
                    for i in range(len(labels))
                ],
                "total_minor": 0,
                "count": 0,
            },
        )
        index = bucket_index(days_past_due(due, as_of), ordered)
        if index is None:
            entry["current_minor"] = int(entry["current_minor"]) + outstanding  # type: ignore[call-overload]
            entry["current_count"] = int(entry["current_count"]) + count  # type: ignore[call-overload]
        else:
            bucket = entry["buckets"][index]  # type: ignore[index]
            bucket["amount_minor"] += outstanding
            bucket["count"] += count
        entry["total_minor"] = int(entry["total_minor"]) + outstanding  # type: ignore[call-overload]
        entry["count"] = int(entry["count"]) + count  # type: ignore[call-overload]
    return [by_currency[c] for c in sorted(by_currency)]
