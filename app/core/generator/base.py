"""The feature-module interface (PLAN.md section 3).

A feature module turns the shared `ProjectCtx` into files. Phase 2 adds `auth`, `jobs`,
`webhooks` as further modules behind this same interface.
"""

from typing import Protocol

from app.core.generator.context import ProjectCtx

# Project-relative path -> file content.
FileTree = dict[str, str]


class FeatureModule(Protocol):
    name: str

    def render(self, project: ProjectCtx) -> FileTree: ...
