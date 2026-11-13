"""Shared code of the operations pack, emitted when the spec declares at least one `packs.operations` block
(validation requires auth and rbac):

  app/operations/__init__.py   package marker
  app/operations/common.py     role checks and tenant scoping (same treatment as the ledger)
  app/operations/geomath.py    pure maths: integer micro-degrees, haversine metres, grid cells, polygons
  app/operations/points.py     the Point request model (micro-degrees or Decimal degrees) and coordinate output

Not a pack of its own: the blocks (geo, location, matching, prediction) are separate modules."""

from pathlib import Path

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.render import read_verbatim
from app.core.validation_operations import operations_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/operations/__init__.py.tpl",
    "app/operations/common.py.tpl",
    "app/operations/geomath.py.tpl",
    "app/operations/points.py.tpl",
)


def operations_enabled(project: ProjectCtx) -> bool:
    return operations_active(project.spec) and project.auth is not None


class OperationsCommonModule:
    name = "operations_common"
    manifest = ModuleManifest(id="operations_common", version="1", depends_on=("crud", "auth"))

    def render(self, project: ProjectCtx) -> FileTree:
        if not operations_enabled(project):
            return {}
        return {template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template) for template in _VERBATIM}
