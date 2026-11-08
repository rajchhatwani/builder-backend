"""The `events` feature: a transactional outbox and a typed in-process event bus.

Emitted only when the spec has `events.enabled`:

  app/events/definitions.py  which fields of which entities are published, adapter, retention (plain data)
  app/events/types.py        typed payload models per entity (from the Read schema, secrets left out)
  app/events/models.py       `ev_outbox` (the events) and `ev_handled` (consumer ledger for idempotency)
  app/events/outbox.py       add_event (in the caller's transaction), already_handled, purge, requeue
  app/events/hooks.py        lifecycle hooks (after_save) + state-log listener that write the events
  app/events/bus.py          envelope, @subscribe registry, tenant context for handlers
  app/events/adapters.py     adapter interface, in-process adapter, Redis Streams stub
  app/events/relay.py        claims rows with FOR UPDATE SKIP LOCKED, delivers in order per record
  app/hooks/subscribers.py   YOUR subscribers (custom zone, written once)
  alembic/versions/0009_events.py, tests/test_events.py
"""

import pprint
import re
from pathlib import Path
from typing import Any

from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import EntityCtx, ProjectCtx
from app.core.generator.features.seed.module import migration_parent as _before_seed
from app.core.generator.features.tests.module import creatable
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_events import events_active
from app.core.validation_notifications import notifications_active
from app.core.validation_providers import providers_active
from app.core.validation_runtime import looks_secret
from app.core.validation_seed import seed_active
from app.core.validation_webhooks import webhooks_active

_TEMPLATES = Path(__file__).parent / "templates"

_VERBATIM = (
    "app/events/__init__.py.tpl",
    "app/events/adapters.py.tpl",
    "app/events/bus.py.tpl",
    "app/events/config.py.tpl",
    "app/events/relay.py.tpl",
    "app/hooks/subscribers.py.tpl",
)


def migration_parent(project: ProjectCtx) -> str:
    """The revision this block's migration follows: the seed's (0008) when the project has it,
    else whatever the seed would have followed."""
    if seed_active(project.spec):
        return "0008"
    return _before_seed(project)


def multi_tenant(project: ProjectCtx) -> bool:
    return project.auth is not None and project.auth.multi_tenant


def event_prefix(entity_name: str) -> str:
    """`LeaveRequest` -> `leave_request` (the part before the dot in an event name)."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", entity_name).lower()


# Same shape as the generated app/core/redact.py key pattern: whatever the log redactor hides, an event
# must not carry either.
_REDACT_KEY_RE = re.compile(
    r"(pass(word|wd)?|secret|token|authorization|signature|api[-_]?key|cookie|credential|"
    r"private[-_]?key|client[-_]?secret)",
    re.IGNORECASE,
)


# Extra, pattern-based filter (fail closed). A name is dropped from event payloads when
#  - its compact form (lower-cased, separators removed: `accessKey`, `access_key`, `ACCESS-KEY` all
#    become `accesskey`) contains one of _SECRET_SUBSTRINGS, or
#  - one of its snake_case / camelCase tokens (a trailing plural `s` ignored) is in _SECRET_TOKENS.
# Short words are matched as whole tokens so `shipping` / `opinion` / `monkey` / `keyboard` stay out of
# the net for the token list; substrings are long enough to be unlikely in an innocent name. A false
# positive only means the field is not announced in the event (read it from the API instead), which
# is the safe direction; add the field to the spec's `observability.extra_redact_keys` for more.
_SECRET_SUBSTRINGS = (
    "accesskey", "signingkey", "secretkey", "privatekey", "apikey", "secret", "password", "passwd",
    "passcode", "passphrase", "credential", "authorization", "bearer", "cookie", "creditcard",
    "cardnumber", "oauth",
)  # fmt: skip
_SECRET_TOKENS = frozenset({
    "salt", "totp", "otp", "pan", "cvv", "cvc", "iban", "ssn", "pin", "auth", "session", "seed", "pwd",
    "token", "signature", "cookie", "bearer",
})  # fmt: skip
_TOKEN_SPLIT = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _pattern_secret(name: str) -> bool:
    compact = re.sub(r"[^a-z0-9]", "", name.lower())
    if any(word in compact for word in _SECRET_SUBSTRINGS):
        return True
    for token in (t.lower() for t in _TOKEN_SPLIT.split(name) if t):
        if token in _SECRET_TOKENS or (token.endswith("s") and token[:-1] in _SECRET_TOKENS):
            return True
    return False


def _secret_name(name: str, extra: tuple[str, ...]) -> bool:
    lowered = name.lower()
    return (
        looks_secret(name)
        or bool(_REDACT_KEY_RE.search(name))
        or _pattern_secret(name)
        or any(k.lower() in lowered for k in extra)
    )


def _extra_keys(project: ProjectCtx) -> tuple[str, ...]:
    obs = project.spec.observability
    return tuple(k for k in (obs.extra_redact_keys if obs is not None else []) if k)


def published_fields(e: EntityCtx, extra: tuple[str, ...] = ()) -> tuple[Any, ...]:
    """The fields an event may carry: not credential-looking, not json (content unknown). Fail closed."""
    return tuple(f for f in e.fields if not _secret_name(f.name, extra) and f.type != "json")


def _fk_columns(e: EntityCtx, extra: tuple[str, ...] = ()) -> tuple[Any, ...]:
    return tuple(fk for fk in e.fks if not _secret_name(fk.column, extra))


def definitions(project: ProjectCtx) -> dict[str, Any]:
    tenant = multi_tenant(project)
    machines = {m.entity for m in project.spec.state_machines}
    extra = _extra_keys(project)
    out: dict[str, Any] = {}
    for e in sorted(project.entities, key=lambda x: x.name):
        names = [
            "id",
            *(f.name for f in published_fields(e, extra)),
            *(fk.column for fk in _fk_columns(e, extra)),
        ]
        out[e.name] = {
            "event": event_prefix(e.name),
            "table": e.table,
            "tenant": tenant and e.tenant_scoped,
            "machine": e.name in machines,
            "fields": [*names, "created_at", "updated_at"],
        }
    return out


_PATCH_TYPES = ("string", "text", "integer", "bigint", "float")


def pick_test_target(project: ProjectCtx) -> dict[str, Any] | None:
    """The entity the generated tests drive through the API: creatable, plain role access, with a field
    that can be patched to a different value."""
    for e in sorted(project.entities, key=lambda x: x.name):
        patch = next((f for f in e.fields if f.patchable and f.type in _PATCH_TYPES), None)
        if (
            creatable(e, project)
            and not e.policy
            and "update" in e.ops
            and patch is not None
            and not e.numbered
        ):
            return {
                "name": e.name,
                "table": e.table,
                "path": e.path,
                "patch_field": patch.name,
                "can_delete": "delete" in e.ops,
                "tenant": bool(multi_tenant(project) and e.tenant_scoped),
                "prefix": event_prefix(e.name),
            }
    return None


class EventsModule:
    name = "events"
    manifest = ModuleManifest(id="events", version="1", depends_on=("crud",))

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not events_active(project.spec):
            return {}
        spec_events = project.spec.events
        assert spec_events is not None
        tenant = multi_tenant(project)
        data = definitions(project)
        extra = _extra_keys(project)
        files: FileTree = {
            template.rsplit(".", 1)[0]: read_verbatim(_TEMPLATES, template)
            for template in _VERBATIM
        }
        nf = project.spec.notifications
        if (
            notifications_active(project.spec)
            and providers_active(project.spec)
            and nf is not None
            and any(t.on_event for t in nf.types)
        ):
            # the notification triggers register themselves when this file is imported (written once)
            files["app/hooks/subscribers.py"] += (
                "\n# Generated notifications are queued by these triggers: keep this import.\n"
                "import app.notifications.triggers  # noqa: E402,F401\n"
            )
        if webhooks_active(project.spec) and project.auth is not None:
            # the webhook fan-out subscribes to the bus: load it wherever subscribers are loaded (relay, API, tests)
            marker = "    importlib.import_module(SUBSCRIBERS_MODULE)\n"
            bus = files["app/events/bus.py"]
            assert bus.count(marker) == 1
            files["app/events/bus.py"] = bus.replace(
                marker, marker + '    importlib.import_module("app.webhooks.fanout")  # platform: webhook fan-out\n'
            )
        files["app/events/definitions.py"] = (
            '"""Events (generated from the spec: change it in the builder).\n\n'
            'Plain data. Only the fields listed under "fields" are ever published."""\n\n'
            "from typing import Any\n\n"
            f"ADAPTER = {spec_events.adapter!r}\n"
            f"RETENTION_DAYS = {spec_events.retention_days}\n"
            f"MULTI_TENANT = {tenant!r}\n\n"
            f"ENTITIES: dict[str, dict[str, Any]] = {pprint.pformat(data, width=96, sort_dicts=True)}\n"
        )
        entities = [
            {
                "name": e.name,
                "event": data[e.name]["event"],
                "machine": data[e.name]["machine"],
                "decls": [
                    *(f.read_decl for f in published_fields(e, extra)),
                    *(fk.read_decl for fk in _fk_columns(e, extra)),
                ],
            }
            for e in sorted(project.entities, key=lambda x: x.name)
        ]
        files["app/events/types.py"] = render_template(
            self._env, "app/events/types.py.j2", entities=entities
        )
        files["app/events/models.py"] = render_template(
            self._env, "app/events/models.py.j2", tenant=tenant
        )
        files["app/events/outbox.py"] = render_template(
            self._env, "app/events/outbox.py.j2", tenant=tenant
        )
        files["app/events/hooks.py"] = render_template(
            self._env,
            "app/events/hooks.py.j2",
            machines=[
                {"name": e.name, "table": e.table}
                for e in sorted(project.entities, key=lambda x: x.name)
                if data[e.name]["machine"]
            ],
        )
        files["alembic/versions/0009_events.py"] = render_template(
            self._env,
            "alembic/versions/0009_events.py.j2",
            down_revision=migration_parent(project),
            tenant=tenant,
        )
        files["tests/test_events.py"] = render_template(
            self._env,
            "tests/test_events.py.j2",
            tenant=tenant,
            auth=project.auth is not None,
            target=pick_test_target(project),
        )
        return files
