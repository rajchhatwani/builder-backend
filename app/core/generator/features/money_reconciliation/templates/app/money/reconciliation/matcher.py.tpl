"""The statement matcher (generated). Pure functions on integers: no database, no clock, no float.

Rules, applied in this order; every pass walks the statement lines by (date, line number) and every ledger
entry is paired at most once (one-to-one):

  1. exact_reference: same amount AND the same non-empty reference; the entry nearest in date wins.
  2. exact:           same amount; the entry nearest in date wins.
  3. tolerance:       |amount difference| <= tolerance; the smallest difference wins, then the nearest date.

Ties are broken by the entry's order (posting time, then id), so the same input always gives the same pairs.
Amounts have the same sign on both sides: positive = increases the account's debit balance."""

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Item:
    id: str
    day: date
    amount: int
    reference: str | None
    order: int  # statement line number, or the ledger entry's position by (posting time, id)


@dataclass(frozen=True)
class Pair:
    line_id: str
    entry_id: str
    method: str
    diff_minor: int  # line amount - entry amount


def _distance(a: date, b: date) -> int:
    return abs((a - b).days)


def match(lines: Sequence[Item], entries: Sequence[Item], tolerance: int = 0) -> list[Pair]:
    if isinstance(tolerance, bool) or not isinstance(tolerance, int) or tolerance < 0:
        raise ValueError("tolerance must be a non-negative int")
    used: set[str] = set()
    by_amount: dict[int, list[Item]] = {}
    for entry in sorted(entries, key=lambda e: e.order):
        by_amount.setdefault(entry.amount, []).append(entry)
    ordered = sorted(lines, key=lambda x: (x.day, x.order, x.id))
    found: dict[str, Pair] = {}

    def best_exact(line: Item, with_reference: bool) -> Item | None:
        choices = [
            e
            for e in by_amount.get(line.amount, [])
            if e.id not in used and (not with_reference or (line.reference and e.reference == line.reference))
        ]
        if not choices:
            return None
        return min(choices, key=lambda e: (_distance(e.day, line.day), e.order))

    for method, with_reference in (("exact_reference", True), ("exact", False)):
        for line in ordered:
            if line.id in found:
                continue
            if with_reference and not line.reference:
                continue
            entry = best_exact(line, with_reference)
            if entry is not None:
                used.add(entry.id)
                found[line.id] = Pair(line.id, entry.id, method, line.amount - entry.amount)
    if tolerance > 0:
        # entries still free, sorted by amount: each line only looks at the amounts inside [a - tol, a + tol]
        free = sorted((e for e in entries if e.id not in used), key=lambda e: (e.amount, e.order, e.id))
        keys = [e.amount for e in free]
        for line in ordered:
            if line.id in found:
                continue
            # same sign only: a credit never pairs with a reversal, whatever the tolerance
            low = bisect_left(keys, line.amount - tolerance)
            high = bisect_right(keys, line.amount + tolerance)
            if line.amount > 0:
                low = max(low, bisect_left(keys, 1))
            else:
                high = min(high, bisect_left(keys, 0))
            if low < high:
                index = min(
                    range(low, high),
                    key=lambda i: (abs(free[i].amount - line.amount), _distance(free[i].day, line.day), free[i].order),
                )
                entry = free.pop(index)
                keys.pop(index)
                found[line.id] = Pair(line.id, entry.id, "tolerance", line.amount - entry.amount)
    return [found[line.id] for line in ordered if line.id in found]
