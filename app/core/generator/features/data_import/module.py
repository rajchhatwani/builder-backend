"""The `data_import` feature (CP-4F2): CSV import and export for generated projects.

  POST /<entity path>/import      multipart file (+ optional `mapping` JSON, `?dry_run=`); entities with a `create` op
  GET  /<entity path>/export.csv  readable fields only, spreadsheet-injection neutralized; entities with a `list` op

  app/imports/csv_import.py  the platform's CSV parser (caps, NUL / UTF-8 checks, coercion, mapping, dedupe key)
  app/imports/fields.py      per-entity field table (what is importable, and its limits)
  app/imports/service.py     the import run: validate, field access, dedupe, one transaction
  app/imports/router.py      the routes (mounted before the entity routers, so `/import` is not an item id)

Emitted only when at least one entity has a `create` operation.
"""

from pathlib import Path

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import EntityCtx, ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template

_TEMPLATES = Path(__file__).parent / "templates"
EXPORT_ROW_CAP = 10_000

_VERBATIM = (
    "app/imports/__init__.py.tpl",
    "app/imports/csv_import.py.tpl",
    "app/imports/service.py.tpl",
)


def import_entities(project: ProjectCtx) -> tuple[EntityCtx, ...]:
    """Entities that get the import (and export) routes: a `create` operation."""
    return tuple(e for e in project.entities if "create" in e.ops)


def caller_may_list(entity: EntityCtx) -> bool:
    """True when everyone who may create may also list the entity, in the same row scope. Only then can the
    import say "duplicate" for a row that exists; otherwise it would tell a create-only caller what exists."""
    if "list" not in entity.ops:
        return False
    by_op = {a.op: a for a in entity.access}
    lst = by_op.get("list")
    if lst is None:  # list is public
        return True
    cre = by_op.get("create")
    if cre is None:  # public create, protected list
        return False
    if lst.policy or cre.policy:  # policies are per action: list vs create is undecidable statically
        return False
    if (lst.owner, lst.tenant, lst.admin_sees_all, lst.match) != (
        cre.owner,
        cre.tenant,
        cre.admin_sees_all,
        cre.match,
    ):
        return False
    if lst.roles and not (cre.roles and set(cre.roles) <= set(lst.roles)):
        return False
    return bool(cre.needs_user or not lst.needs_user)


def _field_literals(project: ProjectCtx, entity: EntityCtx) -> list[str]:
    """One `SpecField(...)` source literal per importable field: scalar fields, then foreign keys.
    Values come from the validated spec; repr() renders them as safe literals."""
    spec_entity = next(s for s in project.spec.entities if s.name == entity.name)
    by_name = {f.name: f for f in spec_entity.fields}
    out: list[str] = []
    for f in entity.fields:
        if f.managed:  # set by the platform (state machine state, numbering), never by the caller
            continue
        sf = by_name[f.name]
        out.append(
            "SpecField("
            + ", ".join(
                (
                    f"name={sf.name!r}",
                    f"type={sf.type!r}",
                    f"required={sf.required!r}",
                    f"unique={sf.unique!r}",
                    f"default={sf.default!r}",
                    f"max_length={sf.max_length!r}",
                    f"min_value={sf.min_value!r}",
                    f"max_value={sf.max_value!r}",
                    f"enum_values={tuple(sf.enum_values) if sf.enum_values else None!r}",
                )
            )
            + ")"
        )
    for fk in entity.fks:
        out.append(
            f"SpecField(name={fk.column!r}, type='uuid', required={fk.required!r}, unique={fk.unique!r})"
        )
    return out


class DataImportModule:
    name = "data_import"
    manifest = ModuleManifest(id="data_import", version="1", depends_on=("crud",))

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        entities = import_entities(project)
        if not entities:
            return {}
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template)
            for template in _VERBATIM
        }
        files["app/imports/fields.py"] = render_template(
            self._env,
            "app/imports/fields.py.j2",
            entities=[(e, _field_literals(project, e)) for e in entities],
        )
        files["app/imports/router.py"] = render_template(
            self._env,
            "app/imports/router.py.j2",
            entities=entities,
            may_list={e.name: caller_may_list(e) for e in entities},
            with_access=any(e.access_ops for e in entities),
            export_cap=EXPORT_ROW_CAP,
        )
        return files
