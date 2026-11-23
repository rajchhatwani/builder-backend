"""Suite identity path (b) and (c): the spec contract, the pure transition rules and the gated generator output."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.generator import generate
from app.core.spec_models import Spec, SpecSuiteMigration
from app.core.suite_migration import (
    MAX_DUAL_DAYS,
    legacy_settings,
    transition_problem,
    window_problems,
)
from app.core.validation import ValidationIssue, validate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"
START, END = "2026-12-01T00:00:00Z", "2027-01-15T00:00:00Z"
LEGACY = "builtin:suite-portal"


def load(name: str = "keycloak_suite") -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data


def with_migration(**migration: Any) -> dict[str, Any]:
    data = load()
    data["auth"]["suite"]["join_state"] = "joined"
    data["auth"]["suite"]["migration"] = {"legacy_issuer": LEGACY, **migration}
    return data


def codes(data: dict[str, Any]) -> set[tuple[str, str]]:
    issues: list[ValidationIssue] = validate(Spec.model_validate(data))
    return {(i.path, i.code) for i in issues}


DUAL = {"state": "dual", "window_started_at": START, "dual_until": END}


# --- validation -----------------------------------------------------------------------------


def test_a_valid_migration_has_no_issues() -> None:
    for state in ({"state": "legacy_read_only"}, DUAL, {"state": "hub_only"}):
        assert codes(with_migration(**state)) == set(), state


def test_a_dual_window_needs_both_instants() -> None:
    for window in ({}, {"dual_until": END}, {"window_started_at": START}):
        found = codes(with_migration(state="dual", **window))
        assert ("auth.suite.migration.dual_until", "dual_window_required") in found, window


def test_the_dual_window_is_at_most_90_days_and_forward() -> None:
    long = {"state": "dual", "window_started_at": START, "dual_until": "2027-03-02T00:00:00Z"}
    assert ("auth.suite.migration.dual_until", "dual_window_too_long") in codes(with_migration(**long))
    edge = {"state": "dual", "window_started_at": START, "dual_until": "2027-03-01T00:00:00Z"}
    assert codes(with_migration(**edge)) == set()  # exactly 90 days
    back = {"state": "dual", "window_started_at": END, "dual_until": START}
    assert ("auth.suite.migration.dual_until", "dual_window_invalid") in codes(with_migration(**back))
    naive = {"state": "dual", "window_started_at": "2026-12-01T00:00:00", "dual_until": "2026-12-20T00:00:00"}
    assert ("auth.suite.migration.window_started_at", "timezone_required") in codes(with_migration(**naive))
    assert MAX_DUAL_DAYS == 90


def test_hub_only_and_legacy_read_only_carry_no_window() -> None:
    for state in ("hub_only", "legacy_read_only"):
        found = codes(with_migration(state=state, dual_until=END, window_started_at=START))
        assert ("auth.suite.migration.dual_until", "window_not_allowed") in found, state


def test_a_migration_needs_a_suite_member_on_keycloak() -> None:
    data = with_migration(state="legacy_read_only")
    data["auth"]["provider"] = "builtin"
    assert ("auth.suite.migration", "migration_requires_keycloak") in codes(data)
    data = with_migration(state="legacy_read_only")
    data["auth"]["suite"]["join_state"] = "none"
    assert ("auth.suite.migration", "migration_requires_suite") in codes(data)


def test_the_state_and_issuer_are_checked() -> None:
    assert ("auth.suite.migration.state", "invalid_value") in codes(with_migration(state="sideways"))
    data = with_migration(state="legacy_read_only")
    del data["auth"]["suite"]["migration"]["legacy_issuer"]
    with pytest.raises(ValidationError):
        Spec.model_validate(data)


def test_the_spec_without_a_migration_is_unchanged() -> None:
    assert Spec.model_validate(load()).auth.suite.migration is None  # type: ignore[union-attr]


# --- transitions ----------------------------------------------------------------------------


def m(state: str, **extra: Any) -> SpecSuiteMigration:
    return SpecSuiteMigration(state=state, legacy_issuer=LEGACY, **extra)


def test_transitions_only_go_forward_one_step_and_hub_only_is_final() -> None:
    dual = m("dual", dual_until="2027-01-15T00:00:00Z", window_started_at="2026-12-01T00:00:00Z")  # type: ignore[arg-type]
    assert transition_problem(None, m("legacy_read_only")) is None
    assert transition_problem(m("legacy_read_only"), dual) is None
    assert transition_problem(dual, m("hub_only")) is None
    assert transition_problem(None, dual) is not None  # skips a step
    assert transition_problem(m("legacy_read_only"), m("hub_only")) is not None
    assert transition_problem(dual, m("legacy_read_only")) is not None  # backwards
    assert transition_problem(m("hub_only"), m("legacy_read_only")) is not None
    assert transition_problem(m("hub_only"), dual) is not None
    assert transition_problem(m("hub_only"), m("hub_only")) is None  # idempotent write
    assert transition_problem(dual, dual) is None  # rewrite the window within the state


def test_window_problems_and_legacy_settings() -> None:
    assert window_problems(m("hub_only")) == []
    assert legacy_settings(m("hub_only")) is None and legacy_settings(None) is None
    settings = legacy_settings(m("legacy_read_only"))
    assert settings == {"state": "legacy_read_only", "issuer": LEGACY, "dual_until": None}


# --- the generator: every migration branch is gated ----------------------------------------


@pytest.fixture(scope="module")
def plain() -> dict[str, str]:
    return generate(Spec.model_validate(load()))


@pytest.fixture(scope="module")
def dual() -> dict[str, str]:
    return generate(Spec.model_validate(with_migration(**DUAL)))


def test_a_suite_without_migration_gets_no_legacy_code(plain: dict[str, str]) -> None:
    assert "app/auth/legacy.py" not in plain and "tests/test_legacy_migration.py" not in plain
    assert "LEGACY" not in plain["app/auth/config.py"] and "legacy" not in plain["app/auth/deps.py"]


def test_the_dual_build_reads_the_window_from_the_generated_config(dual: dict[str, str]) -> None:
    config = dual["app/auth/config.py"]
    assert "LEGACY_STATE = 'dual'" in config and f"LEGACY_ISSUER = '{LEGACY}'" in config
    assert "LEGACY_DUAL_UNTIL: str | None = '2027-01-15T00:00:00+00:00'" in config
    deps = dual["app/auth/deps.py"]
    assert "legacy.verify_access(raw_token, request.method)" in deps
    assert "identity.find_user_id(session, config.LEGACY_ISSUER, subject)" in deps  # never creates a user
    legacy = dual["app/auth/legacy.py"]
    assert "LEGACY_JWT_SECRET" in legacy and "def refusal" in legacy
    assert "tests/test_legacy_migration.py" in dual


def test_hub_only_drops_the_window_from_the_generated_config() -> None:
    files = generate(Spec.model_validate(with_migration(state="hub_only")))
    assert "LEGACY_DUAL_UNTIL: str | None = None" in files["app/auth/config.py"]
    assert "LEGACY_STATE = 'hub_only'" in files["app/auth/config.py"]


@pytest.mark.parametrize("name", ["keycloak_suite", "keycloak_own", "notes_auth", "workspace_auth"])
def test_every_auth_project_gets_the_runbook_and_the_hostile_tests(name: str) -> None:
    files = generate(Spec.model_validate(load(name)))
    runbook = files["docs/IDENTITY-MIGRATION.md"]
    for needle in ("Security checklist", "Pre-account-takeover", "Session invalidation of the loser", "relink", "dual"):
        assert needle.lower() in runbook.lower(), needle
    assert "def test_no_link_on_an_unverified_email" in files["tests/test_identity_migration.py"]
    identity = files["app/auth/identity.py"]
    assert "async def link_verified" in identity and "AUTH_TRUSTED_ISSUERS" in identity
    export = files["app/auth/export.py"]
    for command in ("keycloak-import", "impact", "overlap"):
        assert f'add_parser("{command}")' in export


def test_the_migration_branches_do_not_touch_a_spec_without_them() -> None:
    data = deepcopy(load("keycloak_tenant"))
    files = generate(Spec.model_validate(data))
    assert "LEGACY" not in files["app/auth/config.py"] and "app/auth/legacy.py" not in files


def test_migration_change_rules_are_anchored_to_the_clock_and_never_extend() -> None:
    from datetime import UTC, datetime, timedelta

    from app.core.spec_models import SpecSuiteMigration
    from app.core.suite_migration import migration_change_problem

    now = datetime(2026, 11, 22, tzinfo=UTC)

    def dual(start, end):  # noqa: ANN001, ANN202
        return SpecSuiteMigration(state="dual", legacy_issuer="https://old", window_started_at=start, dual_until=end)

    ro = SpecSuiteMigration(state="legacy_read_only", legacy_issuer="https://old")
    ok = dual(now, now + timedelta(days=30))
    assert migration_change_problem(ro, ok, now) is None
    far = dual(now + timedelta(days=900), now + timedelta(days=960))
    assert migration_change_problem(ro, far, now) is not None
    assert migration_change_problem(ro, dual(now, now + timedelta(days=89)), now) is None
    assert migration_change_problem(ro, dual(now, now + timedelta(days=91)), now) is not None
    longer = dual(now, now + timedelta(days=60))
    assert "never extended" in (migration_change_problem(ok, longer, now) or "")
    assert migration_change_problem(ok, dual(now, now + timedelta(days=10)), now) is None
    hub = SpecSuiteMigration(state="hub_only", legacy_issuer="https://old")
    assert migration_change_problem(ro, hub, now) is not None  # skipping dual
    assert migration_change_problem(hub, ok, now) is not None  # reopening
