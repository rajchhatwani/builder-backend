"""The statement matcher (generated). Pure functions on integers: no database, no clock, no float.

Rules, applied in this order; every pass walks the statement lines by (date, line number) and every ledger
entry is paired at most once (one-to-one):

  1. exact_reference: same amount AND the same non-empty reference; the entry nearest in date wins.
  2. exact:           same amount; the entry nearest in date wins.
  3. tolerance:       |amount difference| <= tolerance; the smallest difference wins, then the nearest date.

Ties are broken by the entry's order (posting time, then id), so the same input always gives the same pairs.
Amounts have the same sign on both sides: positive = increases the account's debit balance."""

from bisect import bisect_left, bisect_right, insort
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


class _Pool:
    """Free entries of one amount (or amount + reference), sorted by (day, order, id): nearest-date lookup is a bisect."""

    def __init__(self) -> None:
        self.keys: list[tuple[int, int, str]] = []
        self.items: dict[tuple[int, int, str], Item] = {}

    def add(self, entry: Item) -> None:
        key = (entry.day.toordinal(), entry.order, entry.id)
        insort(self.keys, key)
        self.items[key] = entry

    def remove(self, entry: Item) -> None:
        key = (entry.day.toordinal(), entry.order, entry.id)
        del self.keys[bisect_left(self.keys, key)]
        del self.items[key]

    def nearest(self, day: date) -> Item | None:
        """The entry nearest in date; equal distance -> the lower order."""
        if not self.keys:
            return None
        target = day.toordinal()
        pos = bisect_left(self.keys, (target,))
        best: tuple[int, int, str] | None = None
        if pos < len(self.keys):
            best = self.keys[pos]  # first entry on the earliest day >= target (lowest order of that day)
        if pos > 0:
            before = self.keys[bisect_left(self.keys, (self.keys[pos - 1][0],))]  # lowest order on the latest earlier day
            if best is None or (target - before[0], before[1]) < (best[0] - target, best[1]):
                best = before
        return self.items[best] if best is not None else None


def match(lines: Sequence[Item], entries: Sequence[Item], tolerance: int = 0) -> list[Pair]:
    if isinstance(tolerance, bool) or not isinstance(tolerance, int) or tolerance < 0:
        raise ValueError("tolerance must be a non-negative int")
    used: set[str] = set()
    by_amount: dict[int, _Pool] = {}
    by_reference: dict[tuple[int, str], _Pool] = {}
    for entry in entries:
        by_amount.setdefault(entry.amount, _Pool()).add(entry)
        if entry.reference:
            by_reference.setdefault((entry.amount, entry.reference), _Pool()).add(entry)
    ordered = sorted(lines, key=lambda x: (x.day, x.order, x.id))
    found: dict[str, Pair] = {}

    def take(entry: Item) -> None:
        used.add(entry.id)
        by_amount[entry.amount].remove(entry)
        if entry.reference:
            by_reference[(entry.amount, entry.reference)].remove(entry)

    def best_exact(line: Item, with_reference: bool) -> Item | None:
        if with_reference:
            pool = by_reference.get((line.amount, line.reference or ""))
        else:
            pool = by_amount.get(line.amount)
        return pool.nearest(line.day) if pool is not None else None

    for method, with_reference in (("exact_reference", True), ("exact", False)):
        for line in ordered:
            if line.id in found:
                continue
            if with_reference and not line.reference:
                continue
            entry = best_exact(line, with_reference)
            if entry is not None:
                take(entry)
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
