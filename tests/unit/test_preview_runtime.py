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


# -- F-001 / S2-002: per-launch secrets -----------------------------------------------------


class _LaunchBox:
    def __init__(self, logs_text: str = "", running: bool = True) -> None:
        self.specs: list[object] = []
        self._logs = logs_text
        self._running = running
        self.destroyed: list[str] = []

    async def check_runtime(self) -> None: ...
    async def create_network(self, sid: str, limits: object) -> str:
        return "net-" + sid

    async def start(self, spec: object) -> None:
        self.specs.append(spec)

    async def ip_of(self, sid: str, net: str) -> str:
        return "10.0.0.2"

    async def is_running(self, sid: str) -> bool:
        return self._running

    async def logs(self, sid: str, tail: int = 15) -> str:
        return self._logs

    async def destroy(self, sid: str) -> None:
        self.destroyed.append(sid)


def _spec(tmp_path: object) -> rt.StackSpec:
    from pathlib import Path

    return rt.StackSpec(
        code_dir=Path(str(tmp_path)), db_sandbox="d" + uuid.uuid4().hex[:8],
        app_sandbox="a" + uuid.uuid4().hex[:8], cpus=0.5, memory_mb=512, db_mb=256,
        ttl_seconds=600, seed_profile=None,
    )  # fmt: skip


async def _run_launch(box: _LaunchBox, spec: rt.StackSpec, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    from app.config import Settings

    async def ok(*a: object, **k: object) -> None: ...

    monkeypatch.setattr(rt, "_wait_db", ok)
    monkeypatch.setattr(rt, "_wait_app", ok)
    await rt.launch(box, spec, Settings(environment="test"))  # type: ignore[arg-type]
    app_spec = box.specs[1]
    return dict(app_spec.env)  # type: ignore[attr-defined]


async def test_launch_gives_every_required_secret_fresh_per_launch(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SECRET_KEY", "platform-root-key-value-0123456789")
    envs = []
    for _ in range(2):
        envs.append(await _run_launch(_LaunchBox(), _spec(tmp_path), monkeypatch))
    a, b = envs
    for name in ("AUTH_JWT_SECRET", "PROVIDER_VAULT_KEY", "STORAGE_SECRET_ACCESS_KEY"):
        assert len(a[name]) >= 48, name
        assert a[name] != b[name], f"{name} must differ between launches"
        assert a[name] != "platform-root-key-value-0123456789"
    assert a["AUTH_JWT_SECRET"] != a["PROVIDER_VAULT_KEY"]  # no value serves two purposes
    assert a["PAYMENTS_WEBHOOK_IP_ALLOWLIST"] and a["KEYCLOAK_PUBLIC_URL"].startswith("http")
    assert "AUTH_JWT_PRIVATE_KEY" not in a  # HS256 app: no RSA key is minted


async def test_launch_mints_an_rsa_key_per_launch_for_rs256_apps(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pathlib import Path

    cfg = Path(str(tmp_path)) / "app" / "auth"
    cfg.mkdir(parents=True)
    (cfg / "config.py").write_text("auth_jwt_private_key: str = Field(min_length=200)\n")
    a = await _run_launch(_LaunchBox(), _spec(tmp_path), monkeypatch)
    b = await _run_launch(_LaunchBox(), _spec(tmp_path), monkeypatch)
    for env in (a, b):
        assert env["AUTH_JWT_PRIVATE_KEY"].startswith("-----BEGIN PRIVATE KEY-----")
        assert len(env["AUTH_JWT_PRIVATE_KEY"]) >= 200
    assert a["AUTH_JWT_PRIVATE_KEY"] != b["AUTH_JWT_PRIVATE_KEY"]


async def test_missing_setting_is_named_and_secrets_are_redacted(
    tmp_path: object,
) -> None:
    fake = "zq" + "Y7" * 20  # not a real secret; split so no full pattern sits in source
    logs = (
        "pydantic_core.ValidationError: 1 validation error for AuthSettings\n"
        "auth_jwt_secret\n  Field required [type=missing]\n"
        f"leaked={fake}\n"
    )
    box = _LaunchBox(logs_text=logs, running=False)
    with pytest.raises(SandboxError) as ei:
        await rt._wait_app(box, "x", "10.0.0.2", timeout=2, secrets_in_use=(fake,))  # type: ignore[arg-type]
    assert "AUTH_JWT_SECRET" in str(ei.value) and fake not in str(ei.value)
    other = _LaunchBox(logs_text=f"boom {fake}", running=False)
    with pytest.raises(SandboxError) as ei2:
        await rt._wait_app(other, "x", "10.0.0.2", timeout=2, secrets_in_use=(fake,))  # type: ignore[arg-type]
    assert fake not in str(ei2.value) and "exited during start" in str(ei2.value)


def test_missing_settings_parser() -> None:
    assert rt.missing_settings("provider_vault_key\n  Field required") == ["PROVIDER_VAULT_KEY"]
    assert rt.missing_settings("PROVIDER_VAULT_KEY is not set") == ["PROVIDER_VAULT_KEY"]
    assert rt.missing_settings("all fine") == []


# -- S2-004: capacity defaults ---------------------------------------------------------------


def test_capacity_limits_are_small_by_default_and_global_is_not_org_overridable() -> None:
    d = PreviewLimits()
    assert d.max_live_total == 6 and d.max_live_per_org >= 1
    assert resolve({"max_live_total": 40}).max_live_total == 40
    assert resolve(None, {"max_live_total": 1}).max_live_total == 6  # org value ignored
    with pytest.raises(AppError):
        validate_limits({"max_live_total": 201})
    from app.services.preview_limits import check_org_overrides

    with pytest.raises(AppError) as e:
        check_org_overrides(None, {"max_live_total": 1.0}, True)
    assert e.value.status_code == 422
