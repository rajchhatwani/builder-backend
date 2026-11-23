"""The `regulated` block (D40 regulated mode, D41 field encryption / tokenisation, D43 customer-managed keys),
emitted only when the spec has an enabled `regulated` block:

  app/regulated/settings.py   which columns are protected and how (data from the spec; no key)
  app/regulated/keys.py       keyring from a file / command / env, purpose-bound subkeys (HKDF)
  app/regulated/crypto.py     AES-256-GCM `rg1:<keyid>:<b64>`, blind index
  app/regulated/fieldtype.py  EncryptedText / TokenisedText column types
  app/regulated/tokens.py     the token vault (`regulated_tokens`)
  app/regulated/orm.py        before_flush listener: blind indexes and tokens
  app/regulated/models.py     the vault table model (only when a field is tokenised)
  app/regulated/reencrypt.py  `python -m app.regulated.reencrypt`
  alembic/versions/0043_regulated.py  the vault table (only when a field is tokenised)
  tests/test_regulated.py, tests/_regulated_support.py

The entity models, the initial migration and the repositories are changed by the crud templates (see `EntityCtx.regulated`);
events leave the protected fields out (see features/events/module.py), so webhooks and notifications never see them."""

import pprint
from pathlib import Path

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.spec_models import Spec
from app.core.validation_regulated import regulated_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/regulated/__init__.py.tpl",
    "app/regulated/errors.py.tpl",
    "app/regulated/keys.py.tpl",
    "app/regulated/crypto.py.tpl",
    "app/regulated/fieldtype.py.tpl",
    "app/regulated/tokens.py.tpl",
    "app/regulated/orm.py.tpl",
    "app/regulated/reencrypt.py.tpl",
    "tests/_regulated_support.py.tpl",
    "tests/test_regulated.py.tpl",
)


def regulated_tokens_active(spec: Spec) -> bool:
    """True when a protected field is tokenised (the project then has the vault table)."""
    return regulated_active(spec) and any(f.mode == "tokenise" for f in spec.regulated.fields)  # type: ignore[union-attr]


def protected_field_names(spec: Spec) -> tuple[str, ...]:
    if not regulated_active(spec):
        return ()
    return tuple(sorted({f.field for f in spec.regulated.fields}))  # type: ignore[union-attr]


class RegulatedModule:
    name = "regulated"
    manifest = ModuleManifest(id="regulated", version="1", depends_on=("crud",))

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        spec = project.spec
        if not regulated_active(spec):
            return {}
        block = spec.regulated
        assert block is not None
        tables = {e.name: e.table for e in project.entities}
        protected: dict[str, dict[str, dict[str, object]]] = {}
        for f in sorted(block.fields, key=lambda x: (tables[x.entity], x.field)):
            protected.setdefault(tables[f.entity], {})[f.field] = {
                "mode": f.mode,
                "searchable": bool(f.searchable and f.mode == "encrypt"),
            }
        obs = spec.observability
        redact_keys = tuple(sorted({*protected_field_names(spec), *(obs.extra_redact_keys if obs is not None else [])}))
        files: FileTree = {template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template) for template in _VERBATIM}
        files["app/regulated/settings.py"] = render_template(
            self._env,
            "app/regulated/settings.py.j2",
            key_provider=block.key_provider,
            protected=pprint.pformat(protected, width=96, sort_dicts=True),
            redact_keys=redact_keys,
        )
        if regulated_tokens_active(spec):
            files["app/regulated/models.py"] = read_verbatim(_TEMPLATES, "app/regulated/models.py.tpl")
            files["alembic/versions/0043_regulated.py"] = render_template(
                self._env, "alembic/versions/0043_regulated.py.j2"
            )
        return files
