"""File-zone manifest (B1-2): every generated path is tagged so later tooling knows what it may touch.

  generated  the platform owns it; regenerating overwrites it
  seeded     written once as a starting point; the project owner is expected to edit it
  custom     the project owner's own code; the platform never overwrites it

Initial classification only: no path moves in this cycle. Rules are checked in order, first match wins;
a path matching no rule is `generated` (fail closed: the platform may only protect what it knows is custom).
"""

import json
from collections.abc import Mapping

from app.core.generator.base import FileTree

ZONES_PATH = "platform/zones.json"
ZONE_VERSION = 1
ZONE_NAMES = ("generated", "seeded", "custom")

# (prefix or exact path, zone)
_RULES: tuple[tuple[str, str], ...] = (
    ("app/custom_routers/", "custom"),
    ("app/hooks/", "custom"),
    ("app/custom/", "custom"),
    ("tests/custom/", "custom"),
    ("app/seed/plan.py", "seeded"),
    ("README.md", "seeded"),
    (".env.example", "seeded"),
    ("docker-compose.yml", "seeded"),
    ("Makefile", "seeded"),
    ("deploy/", "seeded"),
)


def zone_for(path: str) -> str:
    for rule, zone in _RULES:
        if path == rule or (rule.endswith("/") and path.startswith(rule)):
            return zone
    return "generated"


def custom_prefixes() -> list[str]:
    """Folders the project owner writes in (used by the hook gate to tell new files from strays)."""
    return [rule for rule, zone in _RULES if zone == "custom" and rule.endswith("/")]


def merge_regenerated(existing: Mapping[str, str], generated: FileTree) -> tuple[FileTree, list[str]]:
    """Files to write when a project is generated again on top of an existing tree.

    A path in the `custom` zone that already exists is never overwritten: the project owner's file
    (a hook stub with its body, say) wins. Returns (files to write, custom paths that were kept).
    Callers must write only these files, and never delete anything they do not list."""
    out: FileTree = {}
    kept: list[str] = []
    for path, content in generated.items():
        if zone_for(path) == "custom" and path in existing:
            kept.append(path)
        else:
            out[path] = content
    return out, sorted(kept)


def render_zones(files: FileTree) -> str:
    """platform/zones.json content for a finished file tree (the manifest does not list itself)."""
    zones = {path: zone_for(path) for path in sorted(files) if path != ZONES_PATH}
    return json.dumps({"version": ZONE_VERSION, "zones": zones}, indent=2, sort_keys=True) + "\n"
