"""P5: background paths bind the org or are on the code allow-list; non-local startup needs RLS.

Also pins the accepted fail-open design: an UNSET app.organization_id sees everything (sign-in,
webhooks, operator console, background jobs). This is deliberate (S2-010); changing it needs a
design decision, not a quiet edit, so the policy text is asserted here."""

import re
from pathlib import Path

import pytest

from app.config import Settings
from app.core import rls

ROOT = Path(__file__).resolve().parents[2]
_OPENS = re.compile(r"get_session_factory|session_factory|async_sessionmaker|AsyncSession\(")


def test_every_module_opening_its_own_session_binds_or_is_allow_listed() -> None:
    opened = set()
    for path in (ROOT / "app").rglob("*.py"):
        if _OPENS.search(path.read_text()):
            opened.add(path.relative_to(ROOT).as_posix())
    unknown = []
    for rel in sorted(opened):
        src = (ROOT / rel).read_text()
        binds = "rls.bind" in src or "rls.org_context" in src
        if not binds and rel not in rls.UNCONFINED_SESSION_MODULES:
            unknown.append(rel)
    assert not unknown, f"bind the org or add to rls.UNCONFINED_SESSION_MODULES with a reason: {unknown}"


def test_allow_list_has_no_stale_entries_and_every_entry_has_a_reason() -> None:
    for rel, reason in rls.UNCONFINED_SESSION_MODULES.items():
        assert (ROOT / rel).is_file(), rel
        assert len(reason) > 10, rel


def test_unset_guc_is_fail_open_by_design() -> None:
    using = rls._using("projects")
    assert using.startswith(rls._UNSET + " OR "), "unset GUC must stay the documented fail-open"
    assert "FAIL-OPEN on purpose" in Path(rls.__file__).read_text()


def test_parent_child_tables_are_covered() -> None:
    assert {"fields", "scim_group_members"} <= set(rls.ALL_TABLES)


@pytest.mark.parametrize("env", ["staging", "production"])
def test_explicit_non_local_environment_requires_rls(env: str) -> None:
    off = Settings(environment=env, rls_enabled=False)
    assert rls.startup_problem(off) is not None
    on = Settings(environment=env, rls_enabled=True)
    assert rls.startup_problem(on) is None
    assert rls.startup_problem(on, ["role 'x' is a superuser"]) == "role 'x' is a superuser"


def test_local_test_and_unset_environment_are_not_forced() -> None:
    assert rls.startup_problem(Settings(environment="test")) is None
    assert rls.startup_problem(Settings(environment="local")) is None
    assert rls.startup_problem(Settings(_env_file=None)) is None  # unset: not explicit
