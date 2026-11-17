"""Regression tests for audit batch B1-017: generated payments templates, run with stubs."""

import sys
import types
import urllib.error
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
TPL = ROOT / "app/core/generator/features/payments/templates/app/payments"


def _exec(name: str, path: Path, stubs: dict[str, Any]) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__dict__["__file__"] = str(path)
    sys.modules[name] = mod
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), mod.__dict__)  # noqa: S102
    return mod


@pytest.fixture()
def stripe(monkeypatch: pytest.MonkeyPatch) -> Any:
    names = [
        "app.payments",
        "app.payments.config",
        "app.payments.providers",
        "app.payments.providers.base",
    ]
    saved = {n: sys.modules.get(n) for n in names + ["app.payments.providers.stripe"]}
    for n in ("app.payments", "app.payments.providers"):
        sys.modules[n] = types.ModuleType(n)
    cfg = types.ModuleType("app.payments.config")

    class Settings:
        stripe_api_base = "https://api.stripe.test"
        api_base = "https://api.stripe.test"
        payments_provider_timeout_seconds = 1.0

        def secret_key(self) -> str:
            return "k"

        def webhook_secrets(self) -> list[str]:
            return ["s"]

    cfg.__dict__.update(
        PaymentsSettings=Settings,
        WEBHOOK_TOLERANCE_SECONDS=300,
        get_payments_settings=lambda: Settings(),
    )
    sys.modules["app.payments.config"] = cfg
    _exec("app.payments.providers.base", TPL / "providers/base.py.tpl", {})
    mod = _exec("app.payments.providers.stripe", TPL / "providers/stripe.py.tpl", {})
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    yield mod
    for n, v in saved.items():
        if v is None:
            sys.modules.pop(n, None)
        else:
            sys.modules[n] = v


def _http_error(code: int) -> urllib.error.HTTPError:
    import io

    return urllib.error.HTTPError(
        "u", code, "m", {}, io.BytesIO(b'{"error":{"code":"idempotency_key_in_use"}}')
    )  # type: ignore[arg-type]


@pytest.mark.parametrize("code", [409, 408])
def test_f0417_stripe_409_is_retryable_not_rejected(
    stripe: Any, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    calls = {"n": 0}

    def fake_open(_req: Any, timeout: float = 0) -> Any:
        calls["n"] += 1
        raise _http_error(code)

    monkeypatch.setattr(stripe._OPENER, "open", fake_open)
    provider = stripe.StripeProvider()
    base = sys.modules["app.payments.providers.base"]
    with pytest.raises(base.ProviderUnavailable):
        provider._call("POST", "/v1/checkout/sessions", {"a": "b"}, idempotency_key="k1")
    assert calls["n"] == 3


def test_f0422_unicode_digit_timestamp_is_a_clean_rejection(stripe: Any) -> None:
    base = sys.modules["app.payments.providers.base"]
    provider = stripe.StripeProvider()
    for header in ("t=²,v1=" + "a" * 64, "t=٣٣,v1=" + "a" * 64):
        with pytest.raises(base.WebhookRejected):
            provider.verify_webhook(b"{}", {"stripe-signature": header}, now=1000.0)


# --- service.py executed with stubs ---------------------------------------------------------------


class _Result:
    def __init__(self, value: Any = None, row: Any = None) -> None:
        self._value, self._row = value, row

    def scalar_one_or_none(self) -> Any:
        return self._value

    def one(self) -> Any:
        return self._row


class _Session:
    def __init__(self, existing: Any = None, totals: tuple[int, int] = (0, 0)) -> None:
        self.existing, self.totals = existing, totals
        self.added: list[Any] = []
        self.commits = 0

    async def execute(self, _stmt: Any) -> _Result:
        return _Result(self.existing, self.totals)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


@pytest.fixture()
def service() -> Any:
    import sqlalchemy as sa
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

    names = [
        "app.core.errors",
        "app.auth",
        "app.auth.models",
        "app.auth.service",
        "app.payments",
        "app.payments.audit",
        "app.payments.config",
        "app.payments.idempotency",
        "app.payments.jobs",
        "app.payments.payable",
        "app.payments.state",
        "app.payments.models",
        "app.payments.money",
        "app.payments.providers",
        "app.payments.providers.base",
        "app.payments.service",
    ]
    saved = {n: sys.modules.get(n) for n in names}
    for n in ("app.auth", "app.payments", "app.payments.providers"):
        sys.modules[n] = types.ModuleType(n)
    sys.modules["app.auth.models"] = types.SimpleNamespace(AuthUser=object)  # type: ignore[assignment]
    sys.modules["app.auth.service"] = types.SimpleNamespace(effective_roles=lambda r: set(r))  # type: ignore[assignment]
    events: list[tuple[str, dict[str, Any]]] = []

    class AppError(Exception):
        def __init__(self, code: str, message: str, status_code: int = 400) -> None:
            super().__init__(message)
            self.code, self.status_code = code, status_code

    class ConflictError(AppError):
        def __init__(self, message: str) -> None:
            super().__init__("conflict", message, 409)

    class NotFoundError(AppError):
        def __init__(self, message: str) -> None:
            super().__init__("not_found", message, 404)

    sys.modules["app.core.errors"] = types.SimpleNamespace(  # type: ignore[assignment]
        AppError=AppError, ConflictError=ConflictError, NotFoundError=NotFoundError
    )

    async def append(_s: Any, **kw: Any) -> None:
        events.append((kw["event"], kw.get("data") or {}))

    async def noop(*_a: Any, **_k: Any) -> None:
        return None

    sys.modules["app.payments.audit"] = types.SimpleNamespace(  # type: ignore[assignment]
        append=append,
        ACTOR_USER="user",
        ACTOR_PROVIDER="provider",
        ACTOR_SYSTEM="system",
        events=events,
    )
    sys.modules["app.payments.config"] = types.SimpleNamespace(  # type: ignore[assignment]
        REFUND_APPROVAL_THRESHOLD_MINOR=10_000,
        MULTI_TENANT=False,
        ROLES={"refund": ["r"], "operate": ["op"]},
        get_payments_settings=lambda: None,
    )
    sys.modules["app.payments.idempotency"] = types.SimpleNamespace(  # type: ignore[assignment]
        scope_hash=lambda *a: "s",
        request_hash=lambda d: "h",
        attach=noop,
        claim=lambda *a, **k: _claim(),
    )
    sys.modules["app.payments.jobs"] = types.SimpleNamespace(  # type: ignore[assignment]
        enqueue=noop, DISPATCH_REFUND="d", FINISH_PAYMENT="f"
    )
    sys.modules["app.payments.payable"] = types.SimpleNamespace(  # type: ignore[assignment]
        move_status=noop, PAID="p", PARTIALLY_REFUNDED="pr", REFUNDED="r"
    )
    sys.modules["app.payments.money"] = types.SimpleNamespace(normalise_currency=str, to_minor=int)  # type: ignore[assignment]

    class Base(DeclarativeBase):
        pass

    class Payment(Base):
        __tablename__ = "pay_payments"
        id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
        tenant_id: Mapped[int | None] = mapped_column(sa.Integer)
        created_by_id: Mapped[int | None] = mapped_column(sa.Integer)

    class Refund(Base):
        __tablename__ = "pay_refunds"
        id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
        payment_id: Mapped[int] = mapped_column(sa.Integer)
        provider_refund_id: Mapped[str | None] = mapped_column(sa.String)
        tenant_id: Mapped[int | None] = mapped_column(sa.Integer)
        amount_minor: Mapped[int] = mapped_column(sa.Integer)
        currency: Mapped[str] = mapped_column(sa.String)
        status: Mapped[str] = mapped_column(sa.String)
        reason: Mapped[str | None] = mapped_column(sa.String)
        source: Mapped[str | None] = mapped_column(sa.String)
        attempts: Mapped[int] = mapped_column(sa.Integer)
        failure_code: Mapped[str | None] = mapped_column(sa.String)
        requested_by_id: Mapped[int | None] = mapped_column(sa.Integer)
        updated_at: Mapped[Any] = mapped_column(sa.DateTime, nullable=True)

    sys.modules["app.payments.models"] = types.SimpleNamespace(  # type: ignore[assignment]
        Payment=Payment, Refund=Refund, Dispute=object
    )
    base = _exec("app.payments.providers.base", TPL / "providers/base.py.tpl", {})
    sys.modules["app.payments.providers"] = types.SimpleNamespace(get_provider=lambda: None)  # type: ignore[assignment]
    sys.modules["app.payments.state"] = _exec("app.payments.state", TPL / "state.py.tpl", {})
    mod = _exec("app.payments.service", TPL / "service.py.tpl", {})
    mod.base = base  # type: ignore[attr-defined]
    mod.audit_events = events  # type: ignore[attr-defined]
    yield mod
    for n, v in saved.items():
        if v is None:
            sys.modules.pop(n, None)
        else:
            sys.modules[n] = v


async def _claim() -> Any:
    return types.SimpleNamespace(fresh=True, resource_id=None)


def _payment(**kw: Any) -> Any:
    data: dict[str, Any] = dict(
        id=1,
        tenant_id=None,
        status="succeeded",
        amount_minor=50_000,
        refund_reserved_minor=0,
        refunded_minor=0,
        currency="USD",
        payable_id=9,
        provider_session_id="cs_1",
    )
    data.update(kw)
    return types.SimpleNamespace(**data)


@pytest.mark.asyncio
async def test_f0419_split_refunds_cannot_bypass_the_approval_threshold(
    service: Any, monkeypatch: Any
) -> None:
    payment = _payment(refund_reserved_minor=10_000)  # an earlier 10000 refund is already reserved
    session = _Session()

    async def lock(_s: Any, _i: Any) -> Any:
        return payment

    async def noop(*_a: Any, **_k: Any) -> None:
        return None

    async def reload(_s: Any, _i: Any) -> Any:
        return session.added[-1]

    async def get_payment(*_a: Any, **_k: Any) -> Any:
        return payment

    monkeypatch.setattr(service, "_lock_payment", lock)
    monkeypatch.setattr(service, "_recompute_refund_totals", noop)
    monkeypatch.setattr(service, "_try_dispatch", noop)
    monkeypatch.setattr(service, "_reload_refund", reload)
    monkeypatch.setattr(service, "get_payment", get_payment)
    user = types.SimpleNamespace(id=1, roles=["r"])
    refund = await service.request_refund(
        session, user, 1, amount_minor=10_000, reason="duplicate", idempotency_key="k"
    )
    assert refund.status == "pending_approval"


@pytest.mark.asyncio
async def test_f0419_a_single_refund_within_the_threshold_still_needs_no_approval(
    service: Any, monkeypatch: Any
) -> None:
    payment = _payment()
    session = _Session()

    async def lock(_s: Any, _i: Any) -> Any:
        return payment

    async def noop(*_a: Any, **_k: Any) -> None:
        return None

    async def reload(_s: Any, _i: Any) -> Any:
        return session.added[-1]

    monkeypatch.setattr(service, "_lock_payment", lock)
    monkeypatch.setattr(service, "_recompute_refund_totals", noop)
    monkeypatch.setattr(service, "_try_dispatch", noop)
    monkeypatch.setattr(service, "_reload_refund", reload)
    monkeypatch.setattr(service, "get_payment", lambda *a, **k: _ret(payment))
    user = types.SimpleNamespace(id=1, roles=["r"])
    refund = await service.request_refund(
        session, user, 1, amount_minor=10_000, reason="duplicate", idempotency_key="k"
    )
    assert refund.status == "requested"


async def _ret(value: Any) -> Any:
    return value


@pytest.mark.asyncio
async def test_f0421_cancel_provider_outage_on_fallback_is_502_not_500(
    service: Any, monkeypatch: Any
) -> None:
    base = service.base
    payment = _payment(created_by_id=1, status="requires_payment")

    class Provider:
        async def expire_checkout(self, _sid: str) -> Any:
            raise base.ProviderRejected("already_expired")

        async def retrieve_checkout(self, _sid: str) -> Any:
            raise base.ProviderUnavailable("http_503")

    monkeypatch.setattr(service, "get_payment", lambda *a, **k: _ret(payment))
    monkeypatch.setattr(service, "get_provider", lambda: Provider())
    user = types.SimpleNamespace(id=1, roles=["r"])
    with pytest.raises(service.AppError) as caught:
        await service.cancel_payment(_Session(), user, 1)
    assert caught.value.status_code == 502


@pytest.mark.asyncio
async def test_f0418_unchanged_provider_refund_writes_no_new_audit_row(
    service: Any, monkeypatch: Any
) -> None:
    payment = _payment()
    refund = service.Refund(
        id=5,
        payment_id=1,
        provider_refund_id="re_1",
        amount_minor=100,
        currency="USD",
        status="pending",
        attempts=0,
        updated_at=None,
    )
    session = _Session(existing=refund)
    monkeypatch.setattr(service, "_lock_payment", lambda *a, **k: _ret(payment))
    reported = types.SimpleNamespace(
        refund_id="re_1",
        status="pending",
        amount_minor=100,
        currency="USD",
        failure_code=None,
        our_refund_id=None,
    )
    await service.apply_provider_refund(session, 1, reported)
    assert service.audit_events == []
    assert (
        refund.updated_at is not None
    )  # bumped, so the 10-minute recheck does not pick it every pass


@pytest.mark.asyncio
async def test_f0418_a_status_change_is_still_audited(service: Any, monkeypatch: Any) -> None:
    payment = _payment()
    refund = service.Refund(
        id=5,
        payment_id=1,
        provider_refund_id="re_1",
        amount_minor=100,
        currency="USD",
        status="pending",
        attempts=0,
    )
    session = _Session(existing=refund, totals=(100, 100))
    monkeypatch.setattr(service, "_lock_payment", lambda *a, **k: _ret(payment))
    reported = types.SimpleNamespace(
        refund_id="re_1",
        status="succeeded",
        amount_minor=100,
        currency="USD",
        failure_code=None,
        our_refund_id=None,
    )
    await service.apply_provider_refund(session, 1, reported)
    assert [e for e, _ in service.audit_events] == ["refund_succeeded"]


@pytest.mark.asyncio
async def test_f0420_overflowing_provider_refund_is_clamped_to_the_check_constraint(
    service: Any, monkeypatch: Any
) -> None:
    payment = _payment(amount_minor=1000, refund_reserved_minor=1000)
    session = _Session(existing=None, totals=(2000, 1000))  # our pending 1000 + dashboard 1000
    monkeypatch.setattr(service, "_lock_payment", lambda *a, **k: _ret(payment))
    reported = types.SimpleNamespace(
        refund_id="re_9",
        status="succeeded",
        amount_minor=1000,
        currency="USD",
        failure_code=None,
        our_refund_id=None,
    )
    await service.apply_provider_refund(session, 1, reported)
    assert payment.refund_reserved_minor <= payment.amount_minor
    assert payment.refunded_minor <= payment.refund_reserved_minor
    assert "refund_over_reserved" in [e for e, _ in service.audit_events]


def test_f0425_ops_routes_are_refused_in_multi_tenant_projects(service: Any) -> None:
    user = types.SimpleNamespace(id=1, roles=["op"])
    service.require_ops(user)  # single tenant: the operate role is enough
    service.config.MULTI_TENANT = True
    with pytest.raises(service.AppError) as caught:
        service.require_ops(user)  # the queue is shared across tenants: platform-only
    assert caught.value.status_code == 403
    service.config.MULTI_TENANT = False
    with pytest.raises(service.AppError):
        service.require_ops(types.SimpleNamespace(id=2, roles=["x"]))


def test_f0425_ops_router_uses_require_ops() -> None:
    text = (TPL / "router.py.tpl").read_text(encoding="utf-8")
    for fn in ("ops_status", "dead_jobs", "retry_dead_job"):
        body = text.split(f"async def {fn}(")[1].split("\n@router")[0]
        assert "service.require_ops(user)" in body, fn


# --- generated files (F-0423, F-0424) -------------------------------------------------------------


@pytest.fixture(scope="module")
def generated() -> dict[str, str]:
    from app.core.generator import generate
    from app.core.spec_models import Spec

    spec = Spec.model_validate_json(
        (ROOT / "tests/fixtures/specs/payments_stripe.json").read_text(encoding="utf-8")
    )
    assert spec.payments is not None
    spec.payments.scale.kubernetes = True
    return generate(spec)


def test_f0423_migration_revokes_audit_writes_from_the_app_login(generated: dict[str, str]) -> None:
    migration = generated["alembic/versions/0003_payments.py"]
    assert "REVOKE UPDATE, DELETE, TRUNCATE ON pay_audit_log FROM" in migration
    assert "pg_roles" in migration  # only when the role exists
    roles = generated["deploy/sql/roles.sql"]
    assert "ON_ERROR_STOP=1" in roles
    assert "to_regclass('public.pay_audit_log')" in roles  # no failing REVOKE on a fresh database


def test_f0424_k8s_docs_never_apply_jobs_yaml_raw(generated: dict[str, str]) -> None:
    for path in ("deploy/DEPLOYMENT.md", "deploy/k8s/kustomization.yaml"):
        text = generated[path]
        assert "kubectl apply -f deploy/k8s/jobs.yaml" not in text
    assert "-l component=migrate" in generated["deploy/DEPLOYMENT.md"]
    assert "kubectl delete job/" in generated["deploy/DEPLOYMENT.md"]
