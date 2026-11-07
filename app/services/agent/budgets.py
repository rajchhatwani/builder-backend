"""Run budgets and loop / repair detection (architecture 6.1). Pure: no database, no clock.

The driver feeds these functions numbers it read from the database (steps used, cost from the
ledger, elapsed seconds) and persisted tool steps, so the same decisions are reached after a
crash when the driver replays the steps.
"""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.services.agent.contract import StopReason

DEFAULT_MAX_STEPS = 40
DEFAULT_MAX_COST_MICRO_USD = 1_500_000  # 1.50 USD per run (platform total is capped separately)
DEFAULT_MAX_WALL_SECONDS = 900
DEFAULT_MAX_REPAIRS = 3
# Hard ceilings: a stored or requested value can lower a budget but never lift it past these.
CEILINGS = {"max_steps": 200, "max_cost_micro_usd": 100_000_000, "max_wall_seconds": 3600}


@dataclass(frozen=True)
class Budgets:
    max_steps: int = DEFAULT_MAX_STEPS  # model calls per segment (one drive() call)
    max_cost_micro_usd: int = DEFAULT_MAX_COST_MICRO_USD  # per run, from the ai ledger
    max_wall_seconds: int = DEFAULT_MAX_WALL_SECONDS  # per segment
    max_repairs: int = DEFAULT_MAX_REPAIRS  # per failing gate rule

    def as_dict(self) -> dict[str, int]:
        return {
            "max_steps": self.max_steps,
            "max_cost_micro_usd": self.max_cost_micro_usd,
            "max_wall_seconds": self.max_wall_seconds,
            "max_repairs": self.max_repairs,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "Budgets":
        """Tolerant of junk (unknown keys, wrong types, non-positive numbers): falls back to defaults."""
        base = cls()
        values = base.as_dict()
        for key, default in list(values.items()):
            v = (raw or {}).get(key)
            if isinstance(v, int) and not isinstance(v, bool) and v > 0:
                values[key] = min(v, CEILINGS.get(key, v))
            else:
                values[key] = default
        return cls(**values)


def check_limits(b: Budgets, *, steps: int, cost_micro_usd: int, elapsed_seconds: float) -> StopReason | None:
    """First budget that is used up, or None. Order: steps, cost, wall."""
    if steps >= b.max_steps:
        return StopReason("budget_steps", f"{steps} of {b.max_steps} steps used in this segment")
    if cost_micro_usd >= b.max_cost_micro_usd:
        return StopReason(
            "budget_cost", f"{cost_micro_usd} of {b.max_cost_micro_usd} micro-USD used by this run"
        )
    if elapsed_seconds >= b.max_wall_seconds:
        return StopReason("budget_wall", f"{int(elapsed_seconds)} of {b.max_wall_seconds} seconds used")
    return None


def canonical_input(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_input(value).encode()).hexdigest()


class Verdict(StrEnum):
    ok = "ok"
    reflect = "reflect"  # inject a "reflect" system note
    stop = "stop"


class LoopDetector:
    """Same (tool, canonical input) with the same result: 2nd time reflect, 3rd time stop."""

    def __init__(self) -> None:
        self._seen: dict[tuple[str, str, str], int] = {}

    def observe(self, tool: str, tool_input: Any, result: Any) -> Verdict:
        key = (tool, digest(tool_input), digest(result))
        n = self._seen[key] = self._seen.get(key, 0) + 1
        return Verdict.ok if n == 1 else Verdict.reflect if n == 2 else Verdict.stop


def failure_signature(rule_id: str, location: str) -> str:
    return f"{rule_id}@{location}"


class RepairTracker:
    """Gate failures after a repair. The same signature (rule_id + location) a 2nd time:
    reflect; a 3rd time: stop `repairs_exhausted`. Failures of one rule (any location) beyond
    `max_repairs` repairs also stop, so a flapping location cannot dodge the cap."""

    def __init__(self, max_repairs: int = DEFAULT_MAX_REPAIRS) -> None:
        self.max_repairs = max_repairs
        self._by_signature: dict[str, int] = {}
        self._by_rule: dict[str, int] = {}

    def observe(self, failures: Iterable[tuple[str, str]]) -> Verdict:
        """failures: (rule_id, location) pairs of ONE failing tool result."""
        worst = Verdict.ok
        for rule_id, location in failures:
            sig = failure_signature(rule_id, location)
            n = self._by_signature[sig] = self._by_signature.get(sig, 0) + 1
            r = self._by_rule[rule_id] = self._by_rule.get(rule_id, 0) + 1
            if n >= 3 or r > self.max_repairs + 1:
                return Verdict.stop
            if n == 2:
                worst = Verdict.reflect
        return worst


REPAIRS_EXHAUSTED = "repairs_exhausted"
LOOP = "loop"
