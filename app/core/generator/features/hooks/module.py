"""The `hooks` feature: custom logic under contract (B1-8).

Emitted only when the spec declares at least one hook:

  app/hooks_gen/contracts.py   the input and output Pydantic models, generated from the field lists
  app/hooks_gen/registry.py    wires every hook into its entity's lifecycle stage or transition guard
  app/hooks_gen/runtime.py     typed call, wall-clock limit, failure policy
  app/hooks_gen/access.py      the access rules `find_rows` applies: the same as the entity's own list endpoint
  app/platform_sdk/            the only part of the platform a hook body may import. `reads` contract: the
                               rows `find_rows` returns are filtered by the access policies of the acting user
  app/platform_gate.py         gates G0-G7, gate_version 2 (a byte-for-byte copy of app/core/hook_gates.py)
  app/custom/hooks/<name>.py   one stub per hook (zone custom): fixed header and signature, free body
  platform/hooks.json          what the gate checks against: signatures, stub frames, file hashes
  tests/_gen/test_hook_contracts.py

The stubs are in the `custom` zone: `platform/zones.json` says so, and
`app.core.generator.zones.merge_regenerated` never overwrites a custom file that already exists, so
a later generation cannot replace a body somebody wrote.
"""

import ast
import json
import pprint
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core import hook_gates
from app.core.generator.base import FileTree, ModuleManifest
from app.core.generator.context import ProjectCtx
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.generator.zones import custom_prefixes, zone_for
from app.core.spec_models import Spec, SpecHook, SpecHookEffectBudget, SpecHookField
from app.core.validation_notifications import notifications_active
from app.core.validation_providers import providers_active
from app.core.validation_webhooks import webhooks_active
from app.core.validation_hooks import (
    STAGES,
    ceilings_for,
    hooks_active,
    parse_point,
    policy_of,
)

_TEMPLATES = Path(__file__).parent / "templates"
MANIFEST_PATH = "platform/hooks.json"
CONTRACT = "v1"

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PY_TYPE = {
    "string": "str",
    "int": "int",
    "float": "float",
    "decimal": "_decimal.Decimal",
    "bool": "bool",
    "date": "_dt.date",
    "datetime": "_dt.datetime",
    "uuid": "_uuid.UUID",
}
_ALIAS_IMPORT = {
    "_decimal.": "import decimal as _decimal",
    "_dt.": "import datetime as _dt",
    "_uuid.": "import uuid as _uuid",
}
_SAMPLE = {
    "string": "sample",
    "int": 1,
    "float": 1.5,
    "decimal": "1.50",
    "bool": True,
    "date": "2026-01-31",
    "datetime": "2026-01-31T12:00:00+00:00",
    "uuid": "00000000-0000-4000-8000-000000000001",
}
# What a hook body may import from the SDK, and which of those do I/O or read the clock.
SDK_BASE_EXPORTS = (
    "clamp",
    "current_principal",
    "find_rows",
    "is_blank",
    "log",
    "now",
    "pct_diff",
    "slugify",
)
SDK_IO = ("find_rows", "now")
EFFECT_FUNCTIONS = ("notify", "post_webhook", "send_email", "send_sms")  # opt-in effectful tier (H2/H3)
HOOK_INIT_FILES = ("app/custom/__init__.py", "app/custom/hooks/__init__.py")


@dataclass(frozen=True)
class HookView:
    """One hook as the templates and the manifest see it. Every name was validated as an identifier."""

    spec: SpecHook
    entity: str
    stage: str
    transition: str | None
    policy: str

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def file(self) -> str:
        return f"app/custom/hooks/{self.name}.py"

    @property
    def input_model(self) -> str:
        return self.spec.input.name

    @property
    def output_model(self) -> str:
        return self.spec.output.name

    @property
    def signature(self) -> str:
        return f"def {self.name}(data: {self.input_model}) -> {self.output_model}:  {hook_gates.SIGNATURE_COMMENT}"

    @property
    def open_marker(self) -> str:
        return hook_gates.body_markers(self.name)[0]


def views(spec: Spec) -> list[HookView]:
    out: list[HookView] = []
    for h in sorted(spec.hooks, key=lambda x: x.name):
        parsed = parse_point(h.point)
        if parsed is None:  # validation already refused it
            raise RuntimeError(f"bad hook point {h.point!r}")
        entity, stage, transition = parsed
        out.append(HookView(h, entity, stage, transition, policy_of(h)))
    return out


def _check_ident(value: str) -> str:
    if not _IDENT.fullmatch(value):
        raise RuntimeError(f"not an identifier: {value!r}")
    return value


def _model_source(name: str, fields: list[SpecHookField]) -> str:
    lines = [
        f"class {_check_ident(name)}(BaseModel):",
        '    model_config = ConfigDict(extra="forbid", frozen=True)',
    ]
    if fields:
        lines.append("")
    for f in fields:
        annotation = _PY_TYPE[f.type]
        field_name = _check_ident(f.name)
        lines.append(f"    {field_name}: {annotation}" + ("" if f.required else " | None = None"))
    return "\n".join(lines)


def contracts_source(hooks: list[HookView]) -> str:
    """app/hooks_gen/contracts.py: one input and one output model per hook."""
    body = "\n\n\n".join(
        _model_source(model.name, list(model.fields))
        for h in hooks
        for model in (h.spec.input, h.spec.output)
    )
    imports = [imp for token, imp in _ALIAS_IMPORT.items() if token in body]
    names = sorted(m.name for h in hooks for m in (h.spec.input, h.spec.output))
    head = (
        '"""Input and output models of the custom hooks (generated from the spec: change them in the\n'
        'builder, never here)."""\n\n'
    )
    std = "\n".join(sorted(imports, key=lambda i: i.split()[1]))
    pre = (std + "\n\n") if std else ""
    exported = ", ".join(f'"{n}"' for n in names)
    return f"{head}{pre}from pydantic import BaseModel, ConfigDict\n\n__all__ = [{exported}]\n\n\n{body}\n"


def stub_source(h: HookView) -> str:
    """The file an author edits. Only the lines between the body markers are theirs."""
    models = ", ".join(sorted((h.input_model, h.output_model)))
    open_marker, close_marker = hook_gates.body_markers(h.name)
    return (
        f"# {h.file}\n"
        f"# platform:hook {h.name}  point={h.spec.point}  kind={h.spec.kind}  contract={CONTRACT}\n"
        f"from app.hooks_gen.contracts import {models}\n"
        "\n\n"
        f"{h.signature}\n"
        f"{open_marker}\n"
        "    raise NotImplementedError\n"
        f"{close_marker}\n"
    )


def _sample(fields: list[SpecHookField]) -> dict[str, Any]:
    return {f.name: _SAMPLE[f.type] for f in fields}


def effects_on(spec: Spec) -> bool:
    """The effectful tier is generated only for an explicit opt-in that at least one hook uses."""
    fx = spec.hook_effects
    return fx is not None and fx.enabled and any(h.effects for h in spec.hooks)


def effect_functions(spec: Spec) -> list[str]:
    """The effect functions of the SDK: one per platform block the project has switched on."""
    out: list[str] = []
    if webhooks_active(spec):
        out.append("post_webhook")
    if notifications_active(spec):
        out.append("notify")
    if providers_active(spec):
        out += ["send_email", "send_sms"]
    return sorted(out)


def _limits(hooks: list["HookView"]) -> list[dict[str, Any]]:
    out = []
    for h in hooks:
        if not h.spec.effects:
            continue
        eb = h.spec.effect_budget or SpecHookEffectBudget()
        out.append(
            {
                "name": h.name,
                "effects": sorted(h.spec.effects),
                "wall_seconds": h.spec.budget.cpu_ms / 1000 + 0.1,
                "calls_per_effect": eb.calls_per_effect,
                "payload_bytes": eb.payload_bytes,
                "outbound_per_minute": eb.outbound_per_minute,
            }
        )
    return out


def sdk_exports(project: ProjectCtx) -> list[str]:
    names = list(SDK_BASE_EXPORTS)
    if effects_on(project.spec):
        names += effect_functions(project.spec)
    if project.auth is not None:
        names.append("Principal")
    return sorted(names)


def _read_op(entity: Any) -> str | None:
    """The operation whose access rules a hook's read follows: the entity's own list, else its get."""
    for op in ("list", "get"):
        if op in entity.ops:
            return op
    return None


def access_rules(project: ProjectCtx, hooks: list[HookView]) -> dict[str, dict[str, Any]]:
    """Per entity a hook may read: how the entity's own list endpoint is guarded, as pure data.

    mode "roles": the role permissions (`build_access`); "policy": the abac / pbac engine;
    "open": the endpoint is public; "deny": no read endpoint exists, so a hook gets no rows either.
    The generated app/hooks_gen/access.py turns this into the very `Access` the route builds."""
    out: dict[str, dict[str, Any]] = {}
    for name in sorted({n for h in hooks for n in h.spec.reads}):
        entity = project.entity_by_name[name]
        op = _read_op(entity)
        rule: dict[str, Any] = {
            "repo": (f"app.crud.{entity.table}", f"{name}Repository"),
            "read": (f"app.schemas.{entity.table}", f"{name}Read"),
            "op": op,
            "mode": "deny" if op is None else "open",
            "needs_user": False,
            "tenant": False,
            "build": {},
        }
        ctx = next((a for a in entity.access if a.op == op), None)
        if op is not None and ctx is not None:
            rule["needs_user"] = ctx.needs_user or ctx.policy
            rule["tenant"] = ctx.tenant
            if ctx.policy:
                rule["mode"] = "policy"
            else:
                rule["mode"] = "roles"
                build: dict[str, Any] = {}
                if ctx.roles:
                    build["roles"] = tuple(ctx.roles)
                if ctx.owner:
                    build["owner"] = True
                if ctx.admin_sees_all:
                    build["admin_sees_all"] = True
                if ctx.match is not None:
                    build["match"] = (ctx.match[0], ast.literal_eval(ctx.match[1]))
                if ctx.tenant:
                    build["tenant"] = True
                rule["build"] = build
        out[name] = rule
    return out


def definitions(project: ProjectCtx, hooks: list[HookView]) -> dict[str, dict[str, Any]]:
    """Pure data the registry attaches code to."""
    entities = {e.name: e for e in project.spec.entities}
    out: dict[str, dict[str, Any]] = {}
    for h in hooks:
        enums: dict[str, list[str]] = {}
        for f in entities[h.entity].fields:
            if f.type == "enum" and f.name in {o.name for o in h.spec.output.fields}:
                enums[f.name] = list(f.enum_values or [])
        out[h.name] = {
            "name": h.name,
            "point": h.spec.point,
            "entity": h.entity,
            "stage": h.stage,
            "transition": h.transition,
            "kind": h.spec.kind,
            "policy": h.policy,
            "cpu_ms": h.spec.budget.cpu_ms,
            "rows": h.spec.budget.rows,
            "outbound_calls": h.spec.budget.outbound_calls,
            "reads": sorted(h.spec.reads),
            "input_fields": [f.name for f in h.spec.input.fields],
            "output_fields": [f.name for f in h.spec.output.fields],
            "fallback": dict(h.spec.fallback)
            if h.policy == "fallback" and h.spec.fallback
            else None,
            "enums": enums,
        }
    return out


def _field_data(fields: list[SpecHookField]) -> list[dict[str, Any]]:
    return [{"name": f.name, "type": f.type, "required": f.required} for f in fields]


def build_manifest(project: ProjectCtx, files: FileTree) -> str:
    """platform/hooks.json: what `python -m app.platform_gate` checks the project against."""
    hooks = views(project.spec)
    generated = {
        path: hook_gates.sha256_text(content)
        for path, content in files.items()
        if path.startswith("app/") and path.endswith(".py") and zone_for(path) == "generated"
    }
    locked = {path: hook_gates.sha256_text(files[path]) for path in HOOK_INIT_FILES}
    guarded = {
        path: hook_gates.sha256_text(content)
        for path, content in files.items()
        if hook_gates.is_guarded_path(path) and path not in generated and path not in locked
    }
    entries = []
    for h in hooks:
        stub = files[h.file]
        digest = hook_gates.frame_hash(stub, h.name)
        if digest is None:
            raise RuntimeError("stub without body markers")
        entries.append(
            {
                "name": h.name,
                "point": h.spec.point,
                "kind": h.spec.kind,
                "failure_policy": h.policy,
                "file": h.file,
                "function": h.name,
                "input_model": h.input_model,
                "output_model": h.output_model,
                "input_fields": _field_data(h.spec.input.fields),
                "output_fields": _field_data(h.spec.output.fields),
                "budget": h.spec.budget.model_dump(),
                "signature": h.signature,
                "frame_sha256": digest,
            }
        )
        if effects_on(project.spec):
            entries[-1]["effects"] = sorted(h.spec.effects)
            entries[-1]["effect_budget"] = (h.spec.effect_budget or SpecHookEffectBudget()).model_dump()
    manifest = {
        "version": 1,
        "contract": CONTRACT,
        "gate": "app/platform_gate.py",
        "limits": hook_gates.DEFAULT_LIMITS,
        "ceilings": {kind: ceilings_for(kind) for kind in ("pure", "effect")},
        "custom_prefixes": custom_prefixes(),
        "sdk_exports": sdk_exports(project),
        "sdk_io": sorted(SDK_IO + (tuple(effect_functions(project.spec)) if effects_on(project.spec) else ())),
        "contract_exports": sorted(m.name for h in hooks for m in (h.spec.input, h.spec.output)),
        "hooks": entries,
        "locked_sha256": locked,
        "generated_sha256": generated,
        "guarded_sha256": guarded,
    }
    if effects_on(project.spec):
        fx = project.spec.hook_effects
        manifest["effects"] = {
            "enabled": True,
            "trusted_authors_only": True,
            "webhook_hosts": sorted(fx.webhook_hosts) if fx is not None else [],
        }
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


class HooksModule:
    name = "hooks"
    manifest = ModuleManifest(
        id="hooks",
        version="1",
        depends_on=("crud",),
        hook_points=STAGES + ("transition_guard",),
        zones=("app/custom/hooks/", "app/hooks_gen/", "app/platform_sdk/"),
    )

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not hooks_active(project.spec):
            return {}
        hooks = views(project.spec)
        auth = project.auth is not None
        fx_on = effects_on(project.spec)
        files: FileTree = {
            "app/custom/__init__.py": "",
            "app/custom/hooks/__init__.py": "",
            "app/hooks_gen/__init__.py": "",
            "app/hooks_gen/contracts.py": contracts_source(hooks),
            "app/hooks_gen/runtime.py": read_verbatim(_TEMPLATES, "app/hooks_gen/runtime.py.tpl"),
            "app/platform_gate.py": Path(hook_gates.__file__)
            .read_text(encoding="utf-8")
            .replace("\r\n", "\n"),
            "app/hooks_gen/access.py": render_template(
                self._env,
                "app/hooks_gen/access.py.j2",
                auth=auth,
                policy=any(e.policy for e in project.entity_by_name.values()),
                rules=pprint.pformat(access_rules(project, hooks), width=96, sort_dicts=True),
            ),
            "app/platform_sdk/helpers.py": read_verbatim(
                _TEMPLATES, "app/platform_sdk/helpers.py.tpl"
            ),
            "app/platform_sdk/env.py": render_template(
                self._env, "app/platform_sdk/env.py.j2", auth=auth, effects=fx_on
            ),
            "app/platform_sdk/__init__.py": render_template(
                self._env,
                "app/platform_sdk/__init__.py.j2",
                auth=auth,
                exports=sdk_exports(project),
                effects=fx_on,
                effect_imports=", ".join(effect_functions(project.spec)),
            ),
        }
        if fx_on:
            spec = project.spec
            fx = spec.hook_effects
            files["app/platform_sdk/budget.py"] = read_verbatim(_TEMPLATES, "app/platform_sdk/budget.py.tpl")
            files["app/platform_sdk/effects.py"] = render_template(
                self._env,
                "app/platform_sdk/effects.py.j2",
                providers=providers_active(spec),
                webhooks=webhooks_active(spec),
                notifications=notifications_active(spec),
                limits=_limits(hooks),
                webhook_hosts=repr(sorted(fx.webhook_hosts)) if fx is not None else "[]",
            )
        defs = definitions(project, hooks)
        files["app/hooks_gen/registry.py"] = render_template(
            self._env,
            "app/hooks_gen/registry.py.j2",
            hooks=hooks,
            definitions=pprint.pformat(defs, width=96, sort_dicts=True),
        )
        for h in hooks:
            files[h.file] = stub_source(h)
        samples = [
            {
                "name": h.name,
                "file": h.file,
                "input_model": h.input_model,
                "output_model": h.output_model,
                "input_fields": [f.name for f in h.spec.input.fields],
                "required_input": [f.name for f in h.spec.input.fields if f.required],
                "input_sample": pprint.pformat(
                    _sample(list(h.spec.input.fields)), sort_dicts=False
                ),
                "output_sample": pprint.pformat(
                    _sample(list(h.spec.output.fields)), sort_dicts=False
                ),
                "signature": h.signature,
                "open_marker": h.open_marker,
            }
            for h in hooks
        ]
        files["tests/_gen/__init__.py"] = ""
        files["tests/_gen/test_hook_contracts.py"] = render_template(
            self._env, "tests/test_hook_contracts.py.j2", hooks=samples
        )
        return files
