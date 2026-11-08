"""The `notifications` feature: email / SMS / push over the provider adapters (C17).

Emitted only when the spec has `notifications.enabled` (and the project has auth):

  app/notifications/definitions.py  types, channels, variables, default templates (plain data)
  app/notifications/render.py       placeholder substitution with escaping; address checks (pure)
  app/notifications/models.py       `nt_templates`, `nt_preferences`, `nt_deliveries` (delivery log + queue)
  app/notifications/service.py      notify(), templates, preferences: the one place that decides to send
  app/notifications/dispatcher.py   sends queued rows through app.providers with retries and backoff
  app/notifications/triggers.py     queues a type when its `on_event` is delivered (only with on_event types)
  app/notifications/router.py       types, preferences, templates (+ preview), delivery log
  alembic/versions/0021_notifications.py, tests/test_notifications.py
"""

import json
import pprint
from pathlib import Path
from typing import Any

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_notifications import notifications_active
from app.core.validation_providers import providers_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/notifications/__init__.py.tpl",
    "app/notifications/config.py.tpl",
    "app/notifications/dispatcher.py.tpl",
    "app/notifications/models.py.tpl",
    "app/notifications/render.py.tpl",
    "app/notifications/router.py.tpl",
    "app/notifications/service.py.tpl",
)

SUBSCRIBERS_IMPORT = (
    "\n# Generated notifications are queued by these triggers: keep this import.\n"
    "import app.notifications.triggers  # noqa: E402,F401\n"
)


def migration_parent(project: ProjectCtx) -> str:
    """Placeholder: engine.chain_migrations() links every enabled revision into one chain."""
    return "0016"


def multi_tenant(project: ProjectCtx) -> bool:
    return project.auth is not None and project.auth.multi_tenant


def has_event_types(project: ProjectCtx) -> bool:
    nf = project.spec.notifications
    return nf is not None and any(t.on_event for t in nf.types)


def active(project: ProjectCtx) -> bool:
    return notifications_active(project.spec) and providers_active(project.spec) and project.auth is not None


def definitions(project: ProjectCtx) -> dict[str, Any]:
    nf = project.spec.notifications
    assert nf is not None
    types: dict[str, Any] = {}
    for t in sorted(nf.types, key=lambda x: x.name):
        types[t.name] = {
            "category": t.category,
            "channels": list(t.channels),
            "variables": sorted(t.variables),
            "default_enabled": t.default_enabled,
            "on_event": t.on_event,
            "recipient_key_field": t.recipient_key_field,
            "address_fields": dict(sorted(t.address_fields.items())),
            "templates": {
                tpl.channel: {"subject": tpl.subject, "body": tpl.body, "html": tpl.html}
                for tpl in sorted(t.templates, key=lambda x: x.channel)
            },
        }
    return {
        "ADMIN_ROLE": nf.admin_role,
        "MULTI_TENANT": multi_tenant(project),
        "MAX_ATTEMPTS": nf.max_attempts,
        "BACKOFF_SECONDS": nf.backoff_seconds,
        "RETENTION_DAYS": nf.retention_days,
        "TYPES": types,
    }


def _picks(project: ProjectCtx) -> tuple[Any, Any, Any]:
    """(optional type with variables, transactional type, event-triggered type) for the generated tests."""
    nf = project.spec.notifications
    assert nf is not None
    opt = trans = event = None
    for t in sorted(nf.types, key=lambda x: x.name):
        if opt is None and t.category == "optional" and t.variables and t.channels:
            opt = [t.name, t.channels[0], sorted(t.variables)]
        if trans is None and t.category == "transactional" and t.channels:
            trans = [t.name, t.channels[0], sorted(t.variables)]
        if event is None and t.on_event:
            event = [t.name, t.on_event]
    return opt, trans, event


class NotificationsModule:
    name = "notifications"
    manifest = ModuleManifest(id="notifications", version="1", depends_on=("crud", "providers"))

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not active(project):
            return {}
        data = definitions(project)
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template)
            for template in _VERBATIM
        }
        body = "".join(
            f"{key}{': dict[str, Any]' if key == 'TYPES' else ''} = {pprint.pformat(value, width=96, sort_dicts=True)}\n"
            for key, value in data.items()
        )
        files["app/notifications/definitions.py"] = (
            '"""Notifications (generated from the spec: change it in the builder).\n\n'
            "Plain data: types, channels, variables and the DEFAULT templates. A tenant's own templates are in\n"
            'the database (/notifications/templates)."""\n\nfrom typing import Any\n\n' + body
        )
        if has_event_types(project):
            files["app/notifications/triggers.py"] = read_verbatim(_TEMPLATES, "app/notifications/triggers.py.tpl")
        files["alembic/versions/0021_notifications.py"] = render_template(
            self._env, "alembic/versions/0021_notifications.py.j2", down_revision=migration_parent(project)
        )
        picks = _picks(project)
        files["tests/test_notifications.py"] = render_template(
            self._env,
            "tests/test_notifications.py.j2",
            admin_role=data["ADMIN_ROLE"],
            types=data["TYPES"],
            opt=json.dumps(picks[0]),
            trans=json.dumps(picks[1]),
            event=json.dumps(picks[2]),
            tenant=multi_tenant(project),
        )
        return files
