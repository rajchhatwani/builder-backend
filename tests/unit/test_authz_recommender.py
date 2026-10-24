"""The recommender is a scoring table: same answers, same advice, and every point is explained."""

import pytest

from app.core.authz_recommender import Answers, recommend


def model(**answers: object) -> str:
    return str(recommend(Answers(**answers))["model"])  # type: ignore[arg-type]


def test_defaults_pick_the_simplest_model() -> None:
    result = recommend(Answers())
    assert result["model"] == "rbac"
    assert result["cautions"] == []
    assert result["reasons"]


def test_it_is_deterministic() -> None:
    answers = Answers(roles=7, deny_rules=True, audit_needs=True)
    assert recommend(answers) == recommend(answers)


@pytest.mark.parametrize("rule", ["time_or_network_rules", "per_record_rules", "deny_rules"])
def test_rules_rbac_cannot_express_move_away_from_rbac(rule: str) -> None:
    assert model(roles=2, **{rule: True}) != "rbac" or rule == "per_record_rules"
    assert model(roles=6, **{rule: True}) in {"abac", "pbac"}


def test_public_routes_force_rbac_even_with_many_other_needs() -> None:
    result = recommend(
        Answers(roles=9, time_or_network_rules=True, per_record_rules=True, public_routes=True)
    )
    assert result["model"] == "rbac"
    assert any("rbac cannot express" in c for c in result["cautions"])


def test_many_roles_with_conditional_rules_prefer_pbac() -> None:
    assert model(roles=8, per_record_rules=True, deny_rules=True) == "pbac"


def test_a_few_rules_for_everyone_prefer_abac() -> None:
    assert model(roles=1, time_or_network_rules=True) == "abac"


def test_non_developers_editing_rules_pull_toward_rbac_and_add_a_caution() -> None:
    result = recommend(Answers(roles=2, per_record_rules=True, policy_editors="admins"))
    assert (
        result["scores"]["rbac"]
        > recommend(Answers(roles=2, per_record_rules=True))["scores"]["rbac"]
    )
    assert any("review step" in c for c in result["cautions"])


def test_non_rbac_advice_carries_the_default_deny_warning() -> None:
    result = recommend(Answers(roles=6, time_or_network_rules=True))
    assert any("Default deny" in c for c in result["cautions"])
    assert any("no public" in c.lower() for c in result["cautions"])
