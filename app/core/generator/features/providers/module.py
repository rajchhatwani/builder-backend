"""The `providers` feature: provider adapter framework, per-tenant credential vault, test emulator (C15).

Emitted only when the spec has `providers.enabled` (and the project has auth):

  app/providers/definitions.py  adapters allowed per kind, non-secret settings, limits (plain data)
  app/providers/schemas.py      typed request / response models per kind
  app/providers/errors.py       Retryable / Permanent / AuthFailed / RateLimited ...
  app/providers/base.py         the ProviderAdapter protocol and the Credentials holder
  app/providers/registry.py     adapters by (kind, name); the emulator of every kind
  app/providers/emulator.py     deterministic fake adapter: records sends, injects failures
  app/providers/client.py       selection, guard, timeout, retries, breaker, safe logging; decrypts
  app/providers/breaker.py      circuit breaker (open after N failures, half-open probe)
  app/providers/vault.py        AES-256-GCM envelope encryption, rotation, re-encryption
  app/providers/models.py       `provider_credentials`
  app/providers/router.py       admin-only PUT / DELETE / LIST of credentials (write-only secrets)
  app/providers/reencrypt.py    `python -m app.providers.reencrypt`
  app/hooks/providers.py        YOUR adapters (custom zone, written once)
  alembic/versions/0016_providers.py, tests/test_providers.py, tests/_providers_support.py
"""

import pprint
from pathlib import Path
from typing import Any

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.features.events.module import migration_parent as _before_providers
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_events import events_active
from app.core.validation_jobs import jobs_active
from app.core.validation_providers import KINDS, providers_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/providers/__init__.py.tpl",
    "app/providers/base.py.tpl",
    "app/providers/breaker.py.tpl",
    "app/providers/client.py.tpl",
    "app/providers/config.py.tpl",
    "app/providers/emulator.py.tpl",
    "app/providers/errors.py.tpl",
    "app/providers/logsafe.py.tpl",
    "app/providers/models.py.tpl",
    "app/providers/registry.py.tpl",
    "app/providers/reencrypt.py.tpl",
    "app/providers/router.py.tpl",
    "app/providers/schemas.py.tpl",
    "app/providers/vault.py.tpl",
    "app/hooks/providers.py.tpl",
    "tests/_providers_support.py.tpl",
)


_SAMPLE_REQUESTS = {
    "email": 'schemas.EmailRequest(to="ann@example.com", subject="Hello", body="A body that must never be logged")',
    "sms": 'schemas.SmsRequest(to="+15550100", body="A body that must never be logged")',
    "push": 'schemas.PushRequest(device="device-1", title="Hello", body="A body that must never be logged")',
    "payments": 'schemas.PaymentsRequest(action="charge", amount_minor=100, currency="USD", reference="ref-1")',
    "storage": 'schemas.StorageRequest(action="put", key="folder/file.txt", size=3)',
    "llm": 'schemas.LlmRequest(prompt="A prompt that must never be logged")',
    "generic": 'schemas.GenericRequest(operation="ping")',
}


def migration_parent(project: ProjectCtx) -> str:
    """The revision this block's migration follows: the jobs' (0013), else the events' (0009), else
    whatever the events would have followed."""
    if jobs_active(project.spec):
        return "0013"
    if events_active(project.spec):
        return "0009"
    return _before_providers(project)


def multi_tenant(project: ProjectCtx) -> bool:
    return project.auth is not None and project.auth.multi_tenant


def definitions(project: ProjectCtx) -> dict[str, Any]:
    pv = project.spec.providers
    assert pv is not None
    adapters: dict[str, list[str]] = {kind: [] for kind in KINDS}
    settings: dict[str, dict[str, str | int | bool]] = {}
    for a in pv.adapters:
        if a.name not in adapters[a.kind]:
            adapters[a.kind].append(a.name)
        settings[f"{a.kind}/{a.name}"] = dict(sorted(a.settings.items()))
    names: list[str] = []
    for a in pv.adapters:
        if a.name not in names:
            names.append(a.name)
    return {
        "ADMIN_ROLE": pv.admin_role,
        "TIMEOUT_SECONDS": float(pv.timeout_seconds),
        "MAX_ATTEMPTS": pv.max_attempts,
        "BREAKER_FAILURES": pv.breaker_failures,
        "BREAKER_RESET_SECONDS": float(pv.breaker_reset_seconds),
        "MULTI_TENANT": multi_tenant(project),
        "PROVIDERS": names,
        "ADAPTERS": adapters,
        "SETTINGS": settings,
    }


class ProvidersModule:
    name = "providers"
    manifest = ModuleManifest(id="providers", version="1", depends_on=("crud",))

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not providers_active(project.spec) or project.auth is None:
            return {}
        data = definitions(project)
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template)
            for template in _VERBATIM
        }
        body = "".join(
            f"{key} = {pprint.pformat(value, width=96, sort_dicts=True)}\n"
            for key, value in data.items()
        )
        files["app/providers/definitions.py"] = (
            '"""Providers (generated from the spec: change it in the builder).\n\n'
            "Plain data: provider NAMES and non-secret settings. Credentials are never here; each tenant\n"
            'stores its own through /providers/credentials."""\n\n' + body
        )
        files["alembic/versions/0016_providers.py"] = render_template(
            self._env,
            "alembic/versions/0016_providers.py.j2",
            down_revision=migration_parent(project),
        )
        pv = project.spec.providers
        assert pv is not None
        first = (pv.adapters[0].kind, pv.adapters[0].name) if pv.adapters else None
        files["tests/test_providers.py"] = render_template(
            self._env,
            "tests/test_providers.py.j2",
            admin_role=data["ADMIN_ROLE"],
            provider=first[1] if first else "",
            kind=first[0] if first else "",
            request_expr=_SAMPLE_REQUESTS[first[0]] if first else "",
            has_adapter=first is not None,
            tenant=multi_tenant(project),
        )
        return files
