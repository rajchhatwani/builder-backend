"""The `api_edge` feature: idempotency keys, rate limits and quotas, dated API versions (C14).

Emitted only when the spec has `api_edge.enabled`; each part only when its section is present:

  app/api_edge/definitions.py   the settings from the spec (plain data)
  app/api_edge/install.py       wires the middleware, the guard dependency and the session into the app
  app/api_edge/middleware.py    API version, idempotent-request capture, response headers
  app/api_edge/guard.py         rate limit, idempotency claim, quota (an application-wide dependency)
  app/api_edge/caller.py        who is calling (user + tenant) and the client address
  app/api_edge/models.py        api_idempotency, api_rate_buckets, api_quota_usage
  app/api_edge/idempotency.py   claim / replay / finalize / purge
  app/api_edge/ratelimit.py     token buckets in Postgres (atomic upsert)
  app/api_edge/quota.py         per-tenant period counters with a hard cap
  app/api_edge/versioning.py    dated versions and response transformers
  app/api_edge/maintenance.py   `python -m app.api_edge.maintenance` purges old rows
  app/hooks/api_versions.py     YOUR response transformers (custom zone, written once)
  alembic/versions/0012_api_edge.py, tests/test_api_edge.py
"""

import pprint
from pathlib import Path
from typing import Any

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.features.events.module import migration_parent as _before_events
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation import uses_keycloak
from app.core.validation_api_edge import (
    api_edge_active,
    api_edge_tables_active,
    idempotency_active,
    quotas_active,
    rate_limits_active,
    versioning_active,
)
from app.core.validation_events import events_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/api_edge/__init__.py.tpl",
    "app/api_edge/config.py.tpl",
    "app/api_edge/state.py.tpl",
    "app/hooks/api_versions.py.tpl",
)


def migration_parent(project: ProjectCtx) -> str:
    """The revision this block's migration follows: the events' (0009) when the project has them,
    else whatever the events would have followed."""
    if events_active(project.spec):
        return "0009"
    return _before_events(project)


def multi_tenant(project: ProjectCtx) -> bool:
    return project.auth is not None and project.auth.multi_tenant


def _bucket(bucket: Any) -> dict[str, Any] | None:
    if bucket is None:
        return None
    return {"capacity": bucket.capacity, "refill_per_second": float(bucket.refill_per_second)}


def definitions(project: ProjectCtx) -> dict[str, Any]:
    edge = project.spec.api_edge
    assert edge is not None
    idem = edge.idempotency
    rate = edge.rate_limits
    ver = edge.versioning
    return {
        "IDEMPOTENCY": None
        if idem is None
        else {
            "methods": sorted(idem.methods),
            "ttl_hours": idem.ttl_hours,
            "max_response_bytes": idem.max_response_bytes,
        },
        "RATE_LIMITS": None
        if rate is None
        else {
            "user": _bucket(rate.user),
            "tenant": _bucket(rate.tenant),
            "anonymous": _bucket(rate.anonymous),
            "groups": [
                {
                    "name": g.name,
                    "path_prefix": g.path_prefix,
                    "methods": sorted(g.methods),
                    "user": _bucket(g.user),
                    "tenant": _bucket(g.tenant),
                    "cost": g.cost,
                }
                for g in rate.groups
            ],
            "read_fail_open": rate.read_fail_open,
        },
        "QUOTAS": [
            {
                "meter": q.meter,
                "period": q.period,
                "limit": q.limit,
                "path_prefix": q.path_prefix,
                "methods": sorted(q.methods),
                "cost": q.cost,
            }
            for q in sorted(edge.quotas, key=lambda x: x.meter)
        ],
        "VERSIONING": None
        if ver is None
        else {
            "default": ver.default,
            "versions": [
                {"date": v.date, "note": v.note} for v in sorted(ver.versions, key=lambda x: x.date)
            ],
        },
    }


def pick_test_target(project: ProjectCtx) -> dict[str, Any] | None:
    """The entity the generated tests create through the API: creatable, plain role access, and with
    a required string field to read back."""
    from app.core.generator.features.tests.module import creatable

    for e in sorted(project.entities, key=lambda x: x.name):
        if creatable(e, project) and not e.policy and not e.numbered:
            return {
                "name": e.name,
                "table": e.table,
                "path": e.path,
                "tenant": bool(multi_tenant(project) and e.tenant_scoped),
            }
    return None


class ApiEdgeModule:
    name = "api_edge"
    manifest = ModuleManifest(id="api_edge", version="1", depends_on=("crud",))

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not api_edge_active(project.spec):
            return {}
        flags = {
            "idempotency": idempotency_active(project.spec),
            "rate": rate_limits_active(project.spec),
            "quota": quotas_active(project.spec),
            "versioning": versioning_active(project.spec),
            "guarded": api_edge_tables_active(project.spec),
            "auth": project.auth is not None,
            "keycloak": uses_keycloak(project.auth),
            "tenant": multi_tenant(project),
        }
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template)
            for template in _VERBATIM
        }
        data = definitions(project)
        lines = ['"""API edge settings (generated from the spec: change them in the builder).\n\nPlain data."""\n']
        lines.append("from typing import Any\n")
        for name, value in data.items():
            annotation = "list[dict[str, Any]]" if name == "QUOTAS" else "dict[str, Any] | None"
            lines.append(f"{name}: {annotation} = {pprint.pformat(value, width=96, sort_dicts=True)}\n")
        lines.append(f"MULTI_TENANT = {flags['tenant']!r}\n")
        files["app/api_edge/definitions.py"] = "\n".join(lines)
        for template in (
            "app/api_edge/install.py.j2",
            "app/api_edge/middleware.py.j2",
        ):
            files[template.rsplit(".", 1)[0]] = render_template(self._env, template, **flags)
        if flags["guarded"]:
            for template in (
                "app/api_edge/caller.py.j2",
                "app/api_edge/guard.py.j2",
                "app/api_edge/maintenance.py.j2",
                "app/api_edge/models.py.j2",
            ):
                files[template.rsplit(".", 1)[0]] = render_template(self._env, template, **flags)
        if flags["idempotency"]:
            files["app/api_edge/idempotency.py"] = read_verbatim(_TEMPLATES, "app/api_edge/idempotency.py.tpl")
            files["app/api_edge/deferral.py"] = read_verbatim(_TEMPLATES, "app/api_edge/deferral.py.tpl")
        if flags["rate"]:
            files["app/api_edge/ratelimit.py"] = read_verbatim(_TEMPLATES, "app/api_edge/ratelimit.py.tpl")
        if flags["quota"]:
            files["app/api_edge/quota.py"] = read_verbatim(_TEMPLATES, "app/api_edge/quota.py.tpl")
        if flags["versioning"]:
            files["app/api_edge/versioning.py"] = read_verbatim(_TEMPLATES, "app/api_edge/versioning.py.tpl")
        else:
            del files["app/hooks/api_versions.py"]
        if flags["guarded"]:
            files["alembic/versions/0012_api_edge.py"] = render_template(
                self._env,
                "alembic/versions/0012_api_edge.py.j2",
                down_revision=migration_parent(project),
                **flags,
            )
        files["tests/test_api_edge.py"] = render_template(
            self._env,
            "tests/test_api_edge.py.j2",
            target=pick_test_target(project),
            **flags,
        )
        return files
