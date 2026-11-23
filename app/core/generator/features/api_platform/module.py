"""The `api_platform` block (D49 public API keys, D50 installable apps), emitted only when the spec has an enabled
`api_platform` block and the project has auth:

  app/platform_api/settings.py  the spec's data: roles, public entities + fields, limits, apps
  app/platform_api/models.py    api_keys (hash only), api_key_usage (rate windows), platform_audit
  app/platform_api/service.py   key issue / verify / revoke, apps install / uninstall, rate limit, audit
  app/platform_api/router.py    /platform/... admin routes (roles from the spec, default deny, tenant scoped)
  app/platform_api/public.py    /public/v1/... read-only routes, authenticated by `X-API-Key` only
  app/platform_api/events.py    signed app events (HMAC); delivery rides the project's webhooks block
  alembic/versions/0045_api_platform.py, tests/test_platform_api.py

A key is shown once and only its sha256 hash is stored; a key never authenticates an admin route and a user token never
authenticates a public route."""

import pprint
from pathlib import Path

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_api_platform import api_platform_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/platform_api/__init__.py.tpl",
    "app/platform_api/models.py.tpl",
    "app/platform_api/service.py.tpl",
    "app/platform_api/router.py.tpl",
    "app/platform_api/public.py.tpl",
    "app/platform_api/events.py.tpl",
    "tests/test_platform_api.py.tpl",
)

API_PLATFORM_TABLES = ("api_key_usage", "api_keys", "platform_audit")


def api_platform_enabled(project: ProjectCtx) -> bool:
    return api_platform_active(project.spec) and project.auth is not None


def _fmt(value: object) -> str:
    return pprint.pformat(value, width=96, sort_dicts=True)


class ApiPlatformModule:
    name = "api_platform"
    manifest = ModuleManifest(id="api_platform", version="1", depends_on=("crud",))

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        spec = project.spec
        if not api_platform_enabled(project):
            return {}
        block = spec.api_platform
        assert block is not None
        by_name = {e.name: e for e in project.entities}
        entities = {
            pe.entity: {
                "module": f"app.models.{by_name[pe.entity].table}",
                "class": pe.entity,
                "table": by_name[pe.entity].table,
                "plural_path": by_name[pe.entity].path,
                "fields": tuple(pe.fields),
                "sandbox": pe.sandbox,
            }
            for pe in sorted(block.entities, key=lambda x: x.entity)
            if pe.entity in by_name
        }
        apps = {
            a.name: {"title": a.title or a.name, "scopes": tuple(a.scopes), "events": tuple(a.events)}
            for a in sorted(block.apps, key=lambda x: x.name)
        }
        files: FileTree = {template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template) for template in _VERBATIM}
        files["app/platform_api/settings.py"] = render_template(
            self._env,
            "app/platform_api/settings.py.j2",
            roles=_fmt(tuple(sorted(set(block.roles)))),
            entities=_fmt(entities),
            rate_limit=block.rate_limit,
            sandbox_rate_limit=block.sandbox_rate_limit,
            key_ttl_days=block.key_ttl_days,
            apps=_fmt(apps),
            tenant_scoped=bool(spec.auth is not None and spec.auth.multi_tenant),
        )
        files["alembic/versions/0045_api_platform.py"] = render_template(
            self._env, "alembic/versions/0045_api_platform.py.j2"
        )
        return files
