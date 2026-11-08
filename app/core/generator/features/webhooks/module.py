"""The `webhooks` feature: signed webhooks out (from the outbox) and in (raw-body verification) (C13).

Emitted only when the spec has `webhooks.enabled` (it needs auth, events, jobs and providers):

  app/webhooks/definitions.py  allowed events, limits, incoming endpoints (plain data, no secrets)
  app/webhooks/ssrf.py         the destination guard (public addresses only, DNS pinned)
  app/webhooks/egress.py       the only outgoing connection: pinned IP, no redirects, limits
  app/webhooks/signing.py      Standard Webhooks HMAC-SHA256 sign / verify (constant time, tolerance)
  app/webhooks/secrets.py      signing secrets in the credential vault, rotation with an overlap window
  app/webhooks/fanout.py       event -> one delivery + one job per matching subscription
  app/webhooks/delivery.py     one attempt: sign, send, log, retry / fail, auto-disable
  app/webhooks/worker_job.py   the `webhook_delivery` job handler (imported by app/hooks/jobs.py)
  app/webhooks/router.py       admin API (subscriptions, rotation, log) + public incoming endpoint
  app/webhooks/handlers.py     registry for YOUR incoming handlers
  app/webhooks/models.py, maintenance.py
  app/hooks/webhooks.py        YOUR incoming handlers (custom zone, written once)
  alembic/versions/0017_webhooks.py, tests/test_webhooks.py, tests/_webhooks_support.py
"""

import pprint
from pathlib import Path
from typing import Any

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_webhooks import WEBHOOK_JOB, webhooks_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/webhooks/__init__.py.tpl",
    "app/webhooks/delivery.py.tpl",
    "app/webhooks/egress.py.tpl",
    "app/webhooks/fanout.py.tpl",
    "app/webhooks/handlers.py.tpl",
    "app/webhooks/maintenance.py.tpl",
    "app/webhooks/models.py.tpl",
    "app/webhooks/router.py.tpl",
    "app/webhooks/secrets.py.tpl",
    "app/webhooks/signing.py.tpl",
    "app/webhooks/ssrf.py.tpl",
    "app/webhooks/worker_job.py.tpl",
    "app/hooks/webhooks.py.tpl",
    "tests/_webhooks_support.py.tpl",
)


def multi_tenant(project: ProjectCtx) -> bool:
    return project.auth is not None and project.auth.multi_tenant


def active(project: ProjectCtx) -> bool:
    return webhooks_active(project.spec) and project.auth is not None


def definitions(project: ProjectCtx) -> dict[str, Any]:
    wh = project.spec.webhooks
    assert wh is not None
    ports = sorted(set(wh.allowed_ports))
    return {
        "ADMIN_ROLE": wh.admin_role,
        "MULTI_TENANT": multi_tenant(project),
        "JOB": WEBHOOK_JOB,
        "EVENTS": tuple(sorted(wh.events)),
        "MAX_CONSECUTIVE_FAILURES": wh.max_consecutive_failures,
        "SECRET_OVERLAP_HOURS": wh.secret_overlap_hours,
        "TIMEOUT_SECONDS": float(wh.timeout_seconds),
        "MAX_PAYLOAD_BYTES": wh.max_payload_bytes,
        "ALLOW_HTTP": wh.allow_http,
        "ALLOWED_PORTS": ports,
        "INBOUND": {
            e.name: {
                "tolerance_seconds": e.tolerance_seconds,
                "max_body_bytes": e.max_body_bytes,
                "dedupe_days": e.dedupe_days,
            }
            for e in sorted(wh.inbound, key=lambda x: x.name)
        },
    }


class WebhooksModule:
    name = "webhooks"
    manifest = ModuleManifest(id="webhooks", version="1", depends_on=("crud",))

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
            f"{key} = {pprint.pformat(value, width=96, sort_dicts=True)}\n" for key, value in data.items()
        )
        files["app/webhooks/definitions.py"] = (
            '"""Webhooks (generated from the spec: change it in the builder).\n\n'
            'Plain data. No secret is ever here: signing secrets are in the credential vault."""\n\n' + body
        )
        files["alembic/versions/0017_webhooks.py"] = render_template(
            self._env, "alembic/versions/0017_webhooks.py.j2", down_revision="0016"
        )
        events = data["EVENTS"]
        files["tests/test_webhooks.py"] = render_template(
            self._env,
            "tests/test_webhooks.py.j2",
            admin_role=data["ADMIN_ROLE"],
            tenant=data["MULTI_TENANT"],
            event=events[0] if events else "",
            inbound=next(iter(data["INBOUND"]), ""),
        )
        return files
