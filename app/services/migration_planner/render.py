# ruff: noqa: E501
"""Human summary and JSON of a plan."""

from .model import MigrationPlan, Safety

_LABEL = {Safety.safe: "SAFE", Safety.backfill: "NEEDS BACKFILL", Safety.destructive: "DESTRUCTIVE"}


def render_json(plan: MigrationPlan) -> str:
    return plan.to_json()


def render_text(plan: MigrationPlan) -> str:
    if plan.is_empty:
        extra = f" (changed, no schema effect: {', '.join(plan.ignored_sections)})" if plan.ignored_sections else ""
        return f"No schema change.{extra}"
    counts = {s: sum(1 for x in plan.steps if x.safety == s) for s in Safety}
    lines = [
        f"Migration plan: {len(plan.steps)} step(s) - "
        f"{counts[Safety.safe]} safe, {counts[Safety.backfill]} need backfill, {counts[Safety.destructive]} destructive"
    ]
    if plan.requires_confirmation:
        lines.append("CONFIRMATION REQUIRED: destructive steps are refused unless explicitly allowed.")
    for s in plan.steps:
        target = s.entity + (f".{s.field}" if s.field else "")
        lines.append(f"{s.seq:>3}. [{_LABEL[s.safety]}] {s.kind.value} {target}: {s.reason}")
        if s.backfill_strategy:
            lines.append(f"       backfill: {s.backfill_strategy}")
        if s.suggested_action:
            lines.append(f"       action: {s.suggested_action}")
        if s.note:
            lines.append(f"       note: {s.note}")
    if plan.ignored_sections:
        lines.append(f"No schema effect: {', '.join(plan.ignored_sections)}")
    return "\n".join(lines)
