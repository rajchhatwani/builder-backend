"""B3-10: preview limits resolver, token handling, state machine, redaction, rate cap, launch args."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.api.previews import _windows, rate_check
from app.exceptions import AppError
from app.services import preview_runtime as rt
from app.services import preview_service as ps
from app.services.preview_limits import (
    BOUNDS,
    PreviewLimits,
    effective,
    resolve,
    validate_limits,
)
from app.services.sandbox import SandboxError


def test_defaults_match_the_decision() -> None:
    d = PreviewLimits()
    assert (d.max_live_per_user, d.sleep_after_minutes, d.delete_after_days) == (3, 30, 14)
    assert (d.cpus, d.memory_mb, d.db_mb) == (0.5, 512, 1024)
    assert d.rate_per_minute > 0


def test_precedence_defaults_then_platform_then_org() -> None:
    assert resolve(None).memory_mb == 512
    assert resolve({"memory_mb": 256}).memory_mb == 256
    got = resolve({"memory_mb": 256, "cpus": 1.0}, {"memory_mb": 128})
    assert (got.memory_mb, got.cpus) == (128, 1.0)


def test_bounds_are_enforced_on_write() -> None:
    for key, (lo, hi) in BOUNDS.items():
        validate_limits({key: lo})
        validate_limits({key: hi})
        with pytest.raises(AppError):
            validate_limits({key: hi * 2 + 1})
        with pytest.raises(AppError):
            validate_limits({key: lo - 1})
    for bad in ({"nope": 1}, {"cpus": "1"}, {"memory_mb": True}, {"memory_mb": 512.5}):
        with pytest.raises(AppError):
            validate_limits(bad)  # type: ignore[arg-type]


def test_a_hand_edited_row_outside_the_bounds_cannot_widen_anything() -> None:
    got = resolve({"memory_mb": 10**9, "unknown": 1}, {"cpus": 99})
    assert got.memory_mb == 512 and got.cpus == 0.5


def test_kill_switch_and_org_switch_disable() -> None:
    assert effective(False, None).enabled
    e = effective(True, None)
    assert not e.enabled and e.reason == "kill_switch"
    e = effective(False, None, None, org_enabled=False)
    assert not e.enabled and e.reason == "org_disabled"
    assert effective(True, None, None, org_enabled=False).reason == "kill_switch"


def test_token_is_unguessable_hashed_and_compared_exactly() -> None:
    t1, t2 = ps.new_token(), ps.new_token()
    assert t1 != t2 and t1.startswith("bbp_") and len(t1) > 40
    h = ps.hash_token(t1)
    assert h != t1 and len(h) == 64 and t1 not in h
    assert ps.token_matches(h, t1)
    assert not ps.token_matches(h, t2)
    assert not ps.token_matches(h, None)
    assert not ps.token_matches(h, "")
    assert not ps.token_matches(None, t1)  # a wiped preview accepts nothing
    assert not ps.token_matches(h, t1 + "x") and not ps.token_matches(h, t1[:-1])


def test_state_machine() -> None:
    ok = [
        ("starting", "running"), ("starting", "failed"), ("running", "stopping"), ("stopping", "sleeping"),
        ("sleeping", "starting"), ("running", "expired"), ("sleeping", "expired"),
        ("running", "killed"), ("failed", "expired"),
    ]  # fmt: skip
    for a, b in ok:
        assert ps.can_transition(a, b), (a, b)
    bad = [
        ("expired", "running"), ("killed", "starting"), ("failed", "running"),
        ("sleeping", "running"), ("running", "sleeping"),  # waking goes through starting
        ("running", "starting"), ("expired", "killed"),
    ]  # fmt: skip
    for a, b in bad:
        assert not ps.can_transition(a, b), (a, b)
    assert not ps.can_transition("nonsense", "running")


def test_redaction() -> None:
    text = (
        "connect postgresql+asyncpg://app:s3cretpw@db:5432/app\n"
        "Authorization: Bearer abcdefghijklmnop12345\n"
        "STRIPE_API_KEY=sk_live_abcdefghijk password: 'hunter2'\n"
        "plain line stays"
    )
    out = rt.redact(text, ("zzz-known-secret",))
    assert "s3cretpw" not in out and "abcdefghijklmnop12345" not in out
    assert "sk_live_abcdefghijk" not in out and "hunter2" not in out
    assert "plain line stays" in out and "@db:5432/app" in out
    assert rt.redact("x zzz-known-secret y", ("zzz-known-secret",)) == "x [redacted] y"


def test_rate_cap_is_a_sliding_window() -> None:
    pid = uuid.uuid4()
    for i in range(3):
        assert rate_check(pid, 3, now=100.0 + i) is None
    wait = rate_check(pid, 3, now=103.0)
    assert wait is not None and wait >= 1
    assert rate_check(pid, 3, now=161.0) is None  # the first request left the window
    assert rate_check(uuid.uuid4(), 3, now=103.0) is None  # per preview
    _windows.clear()


def test_launch_commands_and_limits() -> None:
    assert rt.app_command(None)[2].startswith("alembic upgrade head && exec python -m uvicorn")
    assert "python -m app.seed --profile demo" in rt.app_command("demo")[2]
    for bad in ("demo; rm -rf /", "$(id)", "A b", ""):
        with pytest.raises(SandboxError):
            rt.app_command(bad)
    spec = rt.StackSpec(
        code_dir=__import__("pathlib").Path("/tmp"),  # noqa: S108
        db_sandbox="a" * 16, app_sandbox="b" * 16,
        cpus=0.5, memory_mb=512, db_mb=1024, ttl_seconds=3600, seed_profile=None,
    )  # fmt: skip
    rt.app_limits(spec).validate()
    rt.db_limits(spec).validate()  # the largest DB still fits the sandbox caps
    assert rt.db_limits(spec).memory == "1280m"


def test_preview_expiry_arithmetic() -> None:
    now = datetime.now(UTC)
    exp = now + timedelta(days=PreviewLimits().delete_after_days)
    assert (exp - now).days == 14


def test_org_override_is_clamped_to_the_platform_default_unless_allowed() -> None:
    from app.services.preview_limits import check_org_overrides

    assert resolve({"memory_mb": 384}, {"memory_mb": 1024}).memory_mb == 384
    assert resolve({"memory_mb": 384}, {"memory_mb": 1024}, allow_above_default=True).memory_mb == 1024
    assert resolve({"memory_mb": 384}, {"memory_mb": 256}).memory_mb == 256  # lowering is fine
    with pytest.raises(AppError):
        check_org_overrides(None, {"max_live_per_user": 4}, False)
    check_org_overrides(None, {"max_live_per_user": 2}, False)
    check_org_overrides(None, {"max_live_per_user": 20}, True)


def test_state_machine_has_a_stopping_step() -> None:
    assert ps.can_transition("running", "stopping") and ps.can_transition("stopping", "sleeping")
    assert not ps.can_transition("running", "sleeping")  # teardown must finish first
    assert not ps.can_transition("stopping", "starting")  # no wake while stopping
