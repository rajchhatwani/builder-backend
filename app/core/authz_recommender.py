"""Which authorization model fits? A small, deterministic scoring table that explains itself.

No machine learning and no hidden weights: each answer adds points to rbac, abac or pbac, and the
reasons that moved the score are returned in plain words. The highest score wins; a tie goes to the
simpler model (rbac < abac < pbac), because a simpler model is easier to review and to get right.

  rbac  roles with per-operation permissions and a few row rules. Public routes are possible.
  abac  rules over attributes of the person, the record and the moment (NIST SP 800-162).
  pbac  the same rules as named policies attached to roles, with allow and deny effects. "PBAC" has
        no standard definition; this is the meaning used here.
"""

from dataclasses import dataclass
from typing import Any

from app.core.enums import AuthorizationModel
from app.core.spec_models import Spec

ORDER = (AuthorizationModel.rbac, AuthorizationModel.abac, AuthorizationModel.pbac)


@dataclass(frozen=True)
class Answers:
    roles: int = 2
    ownership_rules: bool = False
    tenant_rules: bool = False
    time_or_network_rules: bool = False
    per_record_rules: bool = False
    deny_rules: bool = False
    audit_needs: bool = False
    policy_editors: str = "developers"  # developers | admins
    public_routes: bool = False


def answers_from_spec(spec: Spec) -> Answers:
    """What can be read off the current spec; the rest stays at the neutral default."""
    auth = spec.auth
    block = spec.authorization
    return Answers(
        roles=len(auth.roles) if auth is not None else 0,
        ownership_rules=auth is not None
        and any(p.row_rule not in (None, "") for p in auth.permissions),
        tenant_rules=auth is not None and auth.multi_tenant,
        per_record_rules=block is not None and bool(block.policies),
        deny_rules=block is not None and any(p.effect == "deny" for p in block.policies),
    )


def recommend(answers: Answers) -> dict[str, Any]:
    score = {m.value: 0 for m in ORDER}
    reasons: list[str] = []
    cautions: list[str] = []

    def add(rbac: int, abac: int, pbac: int, why: str) -> None:
        score["rbac"] += rbac
        score["abac"] += abac
        score["pbac"] += pbac
        reasons.append(why)

    if answers.roles <= 5:
        add(3, 0, 0, f"{answers.roles} roles is few enough for plain roles and permissions.")
    else:
        add(
            0,
            0,
            2,
            f"{answers.roles} roles is many: attaching named policies to roles scales better.",
        )
    if answers.ownership_rules:
        add(1, 2, 2, "Ownership rules work in every model; policies express them more precisely.")
    if answers.tenant_rules:
        add(0, 1, 1, "Organisation separation is automatic in every model; policies can add more.")
    if answers.time_or_network_rules:
        add(-3, 4, 4, "Time-of-day or network rules need attributes of the moment: only abac/pbac.")
    if answers.per_record_rules:
        add(
            -2, 3, 3, "Rules that depend on a record's own values (status, amount) need attributes."
        )
    if answers.deny_rules:
        add(
            -2,
            2,
            3,
            "A rule that always wins needs a deny effect: abac/pbac, best as named policies.",
        )
    if answers.audit_needs:
        add(0, 1, 2, "Reviewers can read named policies attached to roles as a rulebook.")
    if answers.policy_editors == "admins":
        add(2, 0, 0, "Non-developers will change the rules: the simplest model is safest.")
        cautions.append(
            "Policy conditions are structured data, but reading them still takes care. Plan a "
            "review step before anyone changes a policy in production."
        )
    if answers.public_routes:
        add(5, -10, -10, "Signed-out (public) routes exist only under rbac.")
    if answers.roles >= 3 and (
        answers.per_record_rules or answers.time_or_network_rules or answers.deny_rules
    ):
        add(0, 0, 1, "Several roles with conditional rules: attach the policies per role.")
    elif answers.per_record_rules or answers.time_or_network_rules:
        add(0, 1, 0, "A few rules for everyone are simplest as abac.")

    best = max(ORDER, key=lambda m: (score[m.value], -ORDER.index(m)))
    if best != AuthorizationModel.rbac:
        cautions += [
            "Default deny: every operation on every entity needs an allow policy. Use the "
            "coverage matrix to find operations nobody can do yet.",
            "There are no public (signed-out) routes under abac and pbac.",
            "Try each rule in the simulator with a person, a record and a time before generating.",
        ]
    elif answers.time_or_network_rules or answers.per_record_rules:
        cautions.append(
            "You listed rules that rbac cannot express; they would have to live in your own code."
        )
    alternatives = [f"{m.value} (score {score[m.value]})" for m in ORDER if m != best]
    return {
        "model": best,
        "scores": score,
        "reasons": reasons,
        "cautions": cautions,
        "alternatives": alternatives,
    }
