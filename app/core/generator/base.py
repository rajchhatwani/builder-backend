"""The feature-module interface (PLAN.md section 3).

A feature module turns the shared `ProjectCtx` into files. Phase 2 adds `auth`, `jobs`,
`webhooks` as further modules behind this same interface.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.generator.context import ProjectCtx

# Project-relative path -> file content.
FileTree = dict[str, str]


@dataclass(frozen=True)
class ModuleManifest:
    """What a block declares about itself. Pure data: reading it never renders anything.

    `settings_schema`, `hook_points`, `zones` and `tools` are empty until the work packages that
    fill them (settings B1-6, hooks B1-8, zones B1-2, builder tools Cycle 3) land.
    """

    id: str
    version: str
    depends_on: tuple[str, ...] = ()
    settings_schema: dict[str, Any] = field(default_factory=dict)
    hook_points: tuple[str, ...] = ()
    zones: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()


class FeatureModule(Protocol):
    name: str
    manifest: ModuleManifest

    def render(self, project: ProjectCtx) -> FileTree: ...
