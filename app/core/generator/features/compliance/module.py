"""The `compliance` block (D42 retention + legal hold, D44 consent, D45 break-glass, D46 de-identified export), emitted
only when the spec has an enabled `compliance` block:

  app/compliance/settings.py  the spec's data: roles, retention rules, purposes, break-glass, export treatments
  app/compliance/models.py    legal_holds, consents, break_glass_grants, compliance_audit, retention_runs
  app/compliance/service.py   holds, retention run, consent, break-glass, de-identified export (model layer only)
  app/compliance/router.py    /compliance/... routes (admin roles from the spec, default deny)
  app/compliance/purge.py     `python -m app.compliance.purge [--dry-run]`
  alembic/versions/0044_compliance.py, tests/test_compliance.py

Everything reads and writes through the entity models, so regulated mode (encrypted columns) keeps working; audit
rows hold ids and counts, never a field value."""

import pprint
from pathlib import Path

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_compliance import compliance_active
from app.core.validation_regulated import regulated_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/compliance/__init__.py.tpl",
    "app/compliance/models.py.tpl",
    "app/compliance/service.py.tpl",
    "app/compliance/router.py.tpl",
    "app/compliance/purge.py.tpl",
    "tests/test_compliance.py.tpl",
)

def compliance_enabled(project: ProjectCtx) -> bool:
    return compliance_active(project.spec) and project.auth is not None


COMPLIANCE_TABLES = ("compliance_audit", "break_glass_grants", "consents", "legal_holds", "retention_runs")


def _fmt(value: object) -> str:
    return pprint.pformat(value, width=96, sort_dicts=True)


class ComplianceModule:
    name = "compliance"
    manifest = ModuleManifest(id="compliance", version="1", depends_on=("crud",))

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        spec = project.spec
        if not compliance_enabled(project):
            return {}
        block = spec.compliance
        assert block is not None
        entities = {
            e.name: {"module": f"app.models.{e.table}", "class": e.name, "table": e.table}
            for e in sorted(project.entities, key=lambda x: x.name)
        }
        protected: dict[str, tuple[str, ...]] = {}
        if regulated_active(spec):
            for f in spec.regulated.fields:  # type: ignore[union-attr]
                protected.setdefault(f.entity, ())
                protected[f.entity] = tuple(sorted({*protected[f.entity], f.field}))
        retention = [
            {
                "entity": r.entity,
                "days": r.days,
                "date_field": r.date_field,
                "action": r.action,
                "anonymise_fields": tuple(r.anonymise_fields),
            }
            for r in block.retention
        ]
        export_fields: dict[str, dict[str, str]] = {}
        for ef in block.export_fields:
            export_fields.setdefault(ef.entity, {})[ef.field] = ef.treatment
        export_entities = {x.entity: {"subject_field": x.subject_field} for x in block.export_entities}
        files: FileTree = {template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template) for template in _VERBATIM}
        files["app/compliance/settings.py"] = render_template(
            self._env,
            "app/compliance/settings.py.j2",
            roles=_fmt(tuple(sorted(set(block.roles)))),
            entities=_fmt(entities),
            retention=_fmt(retention),
            purposes=_fmt(tuple(block.consent_purposes)),
            break_glass=_fmt(
                {"enabled": block.break_glass.enabled, "roles": tuple(sorted(set(block.break_glass.roles))),
                 "max_minutes": block.break_glass.max_minutes},
            ),
            export_entities=_fmt(export_entities),
            export_fields=_fmt(export_fields),
            export_consent_purpose=block.export_consent_purpose,
            protected=_fmt(protected),
            tenant_scoped=bool(spec.auth is not None and spec.auth.multi_tenant),
        )
        files["alembic/versions/0044_compliance.py"] = render_template(self._env, "alembic/versions/0044_compliance.py.j2")
        return files
