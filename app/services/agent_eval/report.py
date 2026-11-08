"""Pure report logic: metrics per task, JSON and markdown output, baseline comparison. No I/O to the DB."""

import json
from dataclasses import asdict, dataclass, field
from typing import Any

DEFAULT_TOLERANCE: dict[str, float] = {
    "repairs": 0,  # extra repair loops allowed over the baseline
    "steps": 0,  # extra steps allowed
    "approvals": 0,  # extra human approvals allowed
    "tokens_pct": 10.0,  # token growth allowed, percent
}


@dataclass
class TaskResult:
    task_id: str
    passed: bool
    state: str = ""
    stop_code: str | None = None
    stop_detail: str = ""
    trace: list[str] = field(default_factory=list)
    gate_pass_first_try: bool = False  # the first finish in build was accepted by the gates
    gate_failures: int = 0  # finishes the gates refused
    repairs_used: int = 0
    steps_used: int = 0
    tokens: int = 0  # input + output + cache, from the ledger
    cost_micro_usd: int = 0
    approvals: int = 0  # human decisions needed (proxy for human edits)
    plan_extensions: int = 0  # times the agent left the approved plan
    failures: list[str] = field(default_factory=list)  # assertion messages when not passed


def build_report(results: list[TaskResult], mode: str = "deterministic") -> dict[str, Any]:
    n = len(results)
    ok = sum(1 for r in results if r.passed)
    return {
        "mode": mode,
        "summary": {
            "tasks": n,
            "passed": ok,
            "pass_rate": round(ok / n, 4) if n else 0.0,
            "gate_pass_rate": round(sum(1 for r in results if r.gate_pass_first_try) / n, 4) if n else 0.0,
            "repairs": sum(r.repairs_used for r in results),
            "tokens": sum(r.tokens for r in results),
            "approvals": sum(r.approvals for r in results),
        },
        "tasks": {r.task_id: {**asdict(r), "trace": [] if r.passed else r.trace} for r in sorted(results, key=lambda x: x.task_id)},
    }


def dumps(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def markdown(report: dict[str, Any], regressions: list[str] | None = None) -> str:
    s = report["summary"]
    lines = [
        f"# Agent eval ({report['mode']})",
        "",
        f"Pass rate {s['passed']}/{s['tasks']}, first-try gate pass {s['gate_pass_rate']:.0%}, "
        f"repairs {s['repairs']}, tokens {s['tokens']}, approvals {s['approvals']}.",
        "",
        "| task | passed | state | gate 1st try | repairs | steps | tokens | cost (micro USD) | approvals | stop |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for tid, r in report["tasks"].items():
        lines.append(
            f"| {tid} | {'yes' if r['passed'] else 'NO'} | {r['state']} | {'yes' if r['gate_pass_first_try'] else 'no'} "
            f"| {r['repairs_used']} | {r['steps_used']} | {r['tokens']} | {r['cost_micro_usd']} "
            f"| {r['approvals']} | {r['stop_code'] or ''} |"
        )
    for tid, r in report["tasks"].items():
        for msg in r["failures"]:
            lines.append(f"\n- {tid}: {msg}")
    if regressions is not None:
        lines += ["", "## Regressions vs baseline", ""]
        lines += [f"- {x}" for x in regressions] or ["none"]
    return "\n".join(lines) + "\n"


def compare(
    report: dict[str, Any], baseline: dict[str, Any], tolerance: dict[str, float] | None = None
) -> list[str]:
    """Human-readable regressions of `report` against `baseline` (empty list = none)."""
    tol = {**DEFAULT_TOLERANCE, **(tolerance or {})}
    out: list[str] = []
    if report["summary"]["pass_rate"] < baseline["summary"]["pass_rate"]:
        out.append(f"pass rate down: {baseline['summary']['pass_rate']} -> {report['summary']['pass_rate']}")
    cur, base = report["tasks"], baseline["tasks"]
    for tid in sorted(base):
        if tid not in cur:
            out.append(f"{tid}: task missing from the run")
            continue
        b, c = base[tid], cur[tid]
        if b["passed"] and not c["passed"]:
            out.append(f"{tid}: passed in the baseline, fails now ({'; '.join(c['failures'][:2]) or c['stop_code']})")
            continue
        if b["gate_pass_first_try"] and not c["gate_pass_first_try"]:
            out.append(f"{tid}: gates no longer pass at the first finish")
        for key, label in (("repairs_used", "repairs"), ("steps_used", "steps"), ("approvals", "approvals")):
            if c[key] > b[key] + tol[label]:
                out.append(f"{tid}: {label} up {b[key]} -> {c[key]}")
        if c["tokens"] > b["tokens"] * (1 + tol["tokens_pct"] / 100):
            out.append(f"{tid}: tokens up {b['tokens']} -> {c['tokens']} (> {tol['tokens_pct']}%)")
    return out
