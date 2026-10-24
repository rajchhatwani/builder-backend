"""Simulator and coverage matrix for ABAC / PBAC policies, built from a spec.

Both run the same engine (`authz_engine`) that ships into generated projects, so what the
simulator answers is what the generated API will do for the same subject, row and environment.
Nothing here touches a database.
"""

from collections.abc import Mapping
from typing import Any

from app.core import authz_engine as eng
from app.core.enums import AuthorizationModel
from app.core.generator.features.authz.describe import describe
from app.core.spec_models import Spec
from app.core.validation_authorization import (
    authz_active,
    entity_attributes,
    entity_operations,
    subject_attributes,
)


def policy_set_from_spec(spec: Spec) -> eng.PolicySet:
    """The frozen policy set for a spec that uses abac or pbac. Raises PolicyError when the policy
    data is malformed (validation reports the same problems with paths)."""
    block = spec.authorization
    if block is None or not authz_active(spec):
        raise eng.PolicyError("the project does not use abac or pbac")
    policies = {
        p.id: {
            "effect": p.effect,
            "actions": list(p.actions),
            "when": eng.normalize_node(p.when) if p.when is not None else None,
        }
        for p in block.policies
    }
    if block.model == AuthorizationModel.abac:
        attachments: dict[str, list[str]] = {"*": [p.id for p in block.policies]}
    else:
        attachments = {key: list(ids) for key, ids in sorted(block.attachments.items())}
    return eng.load_policy_set(
        {
            "model": block.model,
            "policies": policies,
            "attachments": attachments,
            "field_types": {e.name: entity_attributes(e) for e in spec.entities},
            "subject_attributes": sorted(subject_attributes(spec.auth)),
        }
    )


def _as_dict(node: Mapping[str, Any] | None) -> dict[str, Any] | None:
    return None if node is None else dict(node)


def _leaf_trace(
    node: Mapping[str, Any],
    ctx: eng.Context,
    resource: Mapping[str, Any],
    types: Mapping[str, str],
) -> list[dict[str, Any]]:
    return [
        {"text": describe(dict(leaf)), "result": eng.eval_node(leaf, ctx, resource, types)}
        for leaf in eng.walk_leaves(node)
    ]


def simulate(
    spec: Spec,
    *,
    entity: str,
    op: str,
    subject: Mapping[str, Any],
    resource: Mapping[str, Any] | None,
    env: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Decide one request and show how: every policy that applies, whether its condition held,
    and the individual comparisons inside it."""
    pset = policy_set_from_spec(spec)
    ctx = eng.Context(subject=dict(subject), env=dict(env or {}))
    types = pset.field_types.get(entity, {})
    row: Mapping[str, Any] = resource or {}
    decision = eng.decide(pset, ctx, entity, op, row)
    trace: list[dict[str, Any]] = []
    roles = list(subject.get("roles") or ())
    for pid, policy in eng.applicable(pset, roles, entity, op):
        when = policy["when"]
        met = True if when is None else eng.eval_node(when, ctx, row, types)
        trace.append(
            {
                "policy": pid,
                "effect": policy["effect"],
                "condition": describe(_as_dict(when)),
                "condition_met": met,
                "leaves": [] if when is None else _leaf_trace(when, ctx, row, types),
            }
        )
    return {
        "allowed": decision.allowed,
        "reason": decision.reason,
        "allow_matched": list(decision.allow_matched),
        "deny_matched": list(decision.deny_matched),
        "trace": trace,
    }


def coverage(spec: Spec) -> list[dict[str, Any]]:
    """Per entity and operation: which policies can allow or deny it, and for whom.

    state  "closed"       no allow policy reaches this operation (nobody can do it)
           "conditional"  every allowing policy has a condition
           "open"         at least one allow policy has no condition: everyone it is attached to
                          can do this (unless a deny policy fires)
    """
    pset = policy_set_from_spec(spec)
    rows: list[dict[str, Any]] = []
    for entity in spec.entities:
        for op in eng.OPERATIONS:
            if op not in entity_operations(entity):
                continue
            allow: list[dict[str, Any]] = []
            deny: list[dict[str, Any]] = []
            principals = ["*", *sorted(p for p in pset.attachments if p != "*")]
            for principal in principals:
                roles = [] if principal == "*" else [principal]
                for pid, policy in eng.applicable(pset, roles, entity.name, op):
                    if principal != "*" and pid in pset.attachments.get("*", ()):
                        continue  # already listed under everyone
                    item = {
                        "policy": pid,
                        "who": "everyone" if principal == "*" else principal,
                        "condition": describe(
                            dict(policy["when"]) if policy["when"] is not None else None
                        ),
                        "unconditional": policy["when"] is None,
                    }
                    (allow if policy["effect"] == "allow" else deny).append(item)
            if not allow:
                state = "closed"
            elif any(a["unconditional"] for a in allow):
                state = "open"
            else:
                state = "conditional"
            rows.append(
                {"entity": entity.name, "op": op, "state": state, "allow": allow, "deny": deny}
            )
    return rows
