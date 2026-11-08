"""Spec-diff migration planner (block F4): plan_migration(old, new) -> MigrationPlan."""

from .model import MigrationPlan, MigrationPlanError, PlanStep, Safety, StepKind
from .planner import plan_migration
from .render import render_json, render_text

__all__ = [
    "MigrationPlan",
    "MigrationPlanError",
    "PlanStep",
    "Safety",
    "StepKind",
    "plan_migration",
    "render_json",
    "render_text",
]
