"""The `authz` feature: attribute- and policy-based access control (ABAC / PBAC).

Emitted only when the spec's authorization model is abac or pbac:

  app/auth/policy.py        the engine, copied byte for byte from app/core/authz_engine.py
  app/auth/policy_data.py   the policies, as data
  app/auth/authorize.py     wires the engine into the routes
  tests/test_authz.py       integrity and wiring tests
  docs/AUTHORIZATION.md     who can do what, in plain language
"""

import hashlib
import pprint
from pathlib import Path
from typing import Any

from app.core import authz_engine as engine
from app.core.enums import AuthorizationModel
from app.core.generator.base import FileTree
from app.core.generator.context import ProjectCtx
from app.core.generator.features.authz.describe import describe
from app.core.generator.render import make_environment, read_verbatim, render_template
from app.core.validation_authorization import (
    FIELD_KIND,
    authz_active,
    subject_attributes,
)

_TEMPLATES = Path(__file__).parent / "templates"


def engine_source() -> str:
    """The engine exactly as the builder runs it (line endings normalised, nothing added)."""
    return Path(engine.__file__).read_text(encoding="utf-8").replace("\r\n", "\n")


def policy_data(project: ProjectCtx) -> dict[str, Any]:
    spec = project.spec
    block = spec.authorization
    assert block is not None
    policies = {
        p.id: {
            "effect": p.effect,
            "actions": list(p.actions),
            "when": engine.normalize_node(p.when) if p.when is not None else None,
        }
        for p in block.policies
    }
    if block.model == AuthorizationModel.abac:
        attachments = {"*": [p.id for p in block.policies]}
    else:
        attachments = {key: list(ids) for key, ids in sorted(block.attachments.items())}
    field_types: dict[str, dict[str, str]] = {}
    for entity_ctx in project.entities:
        entity = next(e for e in spec.entities if e.name == entity_ctx.name)
        types = {"id": "uuid", "created_at": "datetime", "updated_at": "datetime"}
        if entity_ctx.owned:
            types["created_by_id"] = "uuid"
        for f in entity.fields:
            kind = FIELD_KIND.get(f.type)
            if kind is not None:
                types[f.name] = kind
        field_types[entity.name] = dict(sorted(types.items()))
    return {
        "model": block.model,
        "policies": policies,
        "attachments": attachments,
        "field_types": field_types,
        "subject_attributes": sorted(subject_attributes(spec.auth)),
    }


def render_policy_data(data: dict[str, Any]) -> str:
    body = pprint.pformat(data, width=88, sort_dicts=True)
    return (
        '"""Authorization policies (generated from the spec: change them in the builder).\n\n'
        "Read once at start-up by app/auth/authorize.py. A malformed entry stops the application\n"
        'from starting rather than being skipped."""\n\n'
        f"POLICY_DATA = {body}\n"
    )


def _always_denied(data: dict[str, Any], project: ProjectCtx) -> list[tuple[str, str]]:
    """(entity, op) pairs refused outright because of an unconditional deny that applies to all."""
    everyone = set(data["attachments"].get("*", ()))
    pairs: set[tuple[str, str]] = set()
    for pid in sorted(everyone):
        policy = data["policies"][pid]
        if policy["effect"] != "deny" or policy["when"] is not None:
            continue
        for entity in project.entities:
            for op in entity.ops:
                if any(
                    a == "*" or a == f"{entity.name}.{op}" or a == f"{entity.name}.*"
                    for a in policy["actions"]
                ):
                    pairs.add((entity.name, op))
    return sorted(pairs)


def _rows_for_docs(data: dict[str, Any]) -> list[dict[str, Any]]:
    carriers: dict[str, list[str]] = {}
    for principal, ids in data["attachments"].items():
        for pid in ids:
            carriers.setdefault(pid, []).append(
                "everyone signed in" if principal == "*" else f"role {principal}"
            )
    return [
        {
            "id": pid,
            "effect": policy["effect"],
            "actions": ", ".join(policy["actions"]),
            "who": ", ".join(carriers.get(pid, ["nobody"])),
            "when": describe(policy["when"]),
        }
        for pid, policy in data["policies"].items()
    ]


class AuthzModule:
    name = "authz"

    def __init__(self) -> None:
        self._env = make_environment(_TEMPLATES)

    def render(self, project: ProjectCtx) -> FileTree:
        if not authz_active(project.spec) or project.auth is None:
            return {}
        data = policy_data(project)
        engine_text = engine_source()
        data_text = render_policy_data(data)
        context = {
            "model": data["model"],
            "engine_sha256": hashlib.sha256(engine_text.encode("utf-8")).hexdigest(),
            "always_denied_literal": repr(tuple(_always_denied(data, project))),
            "list_routes_literal": repr(
                tuple(sorted(f"/{e.path}" for e in project.entities if "list" in e.ops))
            ),
            "policy_rows": _rows_for_docs(data),
            "project_name": project.name,
            "subject_attributes": data["subject_attributes"],
            "multi_tenant": bool(project.auth.multi_tenant),
        }
        return {
            "app/auth/policy.py": engine_text,
            "app/auth/policy_data.py": data_text,
            "app/auth/authorize.py": read_verbatim(_TEMPLATES, "app/auth/authorize.py.tpl"),
            "tests/test_authz.py": render_template(self._env, "tests/test_authz.py.j2", **context),
            "docs/AUTHORIZATION.md": render_template(
                self._env, "docs/AUTHORIZATION.md.j2", **context
            ),
        }
