"""CP-6A FORGE-A: the open LOW findings of Cycle 5 for the money and booking features.

Generated services are executed with a recording fake session (no database): the statements and commits a call
issues are asserted, never the rows. Database behaviour of the booking guard is proven by the e2e stack; here the
migration text is pinned."""

import ast
import json
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase

from app.core.generator import generate
from app.core.spec_models import Spec
from app.core.validation import validate

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _raw(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _files(name: str) -> dict[str, str]:
    return generate(Spec.model_validate(_raw(name)))


# --- harness: execute generated modules under their dotted names ---------------------------------------------


class _AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, details: Any = None) -> None:
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details


def _stub(name: str, **attrs: Any) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    return module


class _Loaded:
    def __init__(self, files: dict[str, str], names: list[str], stubs: dict[str, types.ModuleType]) -> None:
        self.saved = {n: sys.modules.get(n) for n in [*names, *stubs]}
        self.mods: dict[str, types.ModuleType] = {}
        for name, module in stubs.items():
            sys.modules[name] = module
        for dotted in names:
            module = types.ModuleType(dotted)
            sys.modules[dotted] = module
            self.mods[dotted] = module
            parent = dotted.rpartition(".")[0]
            if parent in sys.modules:
                setattr(sys.modules[parent], dotted.rpartition(".")[2], module)
        for dotted in names:
            path = dotted.replace(".", "/") + ".py"
            if path in files:
                exec(compile(files[path], path, "exec"), self.mods[dotted].__dict__)  # noqa: S102

    def close(self) -> None:
        for name, value in self.saved.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def _base_stub() -> dict[str, types.ModuleType]:
    class Base(DeclarativeBase):
        pass

    return {
        "app.models": _stub("app.models"),
        "app.models._base": _stub("app.models._base", Base=Base, utcnow=lambda: datetime.now(UTC)),
        "app.core": _stub("app.core"),
        "app.core.errors": _stub("app.core.errors", AppError=_AppError),
    }


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def scalar_one(self) -> Any:
        return self.rows[0]

    def scalar_one_or_none(self) -> Any:
        return self.rows[0] if self.rows else None

    def scalars(self) -> "_Result":
        return self

    def all(self) -> list[Any]:
        return list(self.rows)

    def __iter__(self) -> Any:
        return iter(self.rows)


class FakeSession:
    """Records every statement (compiled text + params) and commit; `route(sql)` returns the rows for it."""

    def __init__(self, route: Any) -> None:
        self.route = route
        self.sql: list[str] = []
        self.params: list[dict[str, Any]] = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt: Any, params: Any = None) -> _Result:
        compiled = stmt.compile(dialect=postgresql.dialect())
        text = str(compiled)
        self.sql.append(text)
        self.params.append(dict(compiled.params))
        return _Result(self.route(text, dict(compiled.params)))

    async def scalar(self, stmt: Any) -> Any:
        return (await self.execute(stmt)).scalar_one()

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


# --- 5B L3: payout seller ------------------------------------------------------------------------------------


def test_payout_seller_is_validated_and_the_docs_say_payouts_are_irreversible() -> None:
    files = _files("money_marketplace")
    loaded = _Loaded(files, ["app.money", "app.money.invoicing", "app.money.invoicing.config", "app.money.invoicing.schemas"], {})
    try:
        schemas = loaded.mods["app.money.invoicing.schemas"]
        key, inv = "k1", "00000000-0000-0000-0000-000000000001"
        assert schemas.PayoutRunIn(idempotency_key=key, invoice_id=inv, seller="shop-1").seller == "shop-1"
        for bad in ("", " ", " shop", "shop ", "shop\n", "sh\x00op", "sh\top", "\x7fshop", "a" * 65):
            with pytest.raises(ValidationError):
                schemas.PayoutRunIn(idempotency_key=key, invoice_id=inv, seller=bad)
    finally:
        loaded.close()
    router = files["app/money/invoicing/payouts_router.py"]
    assert "irreversible" in router and "operator-chosen label" in router and "not checked against the invoice counterparty" in router
    schemas_src = files["app/money/invoicing/schemas.py"]
    assert "irreversible" in schemas_src.lower() and "operator-chosen label" in schemas_src


# --- 5B L4: no query per row ---------------------------------------------------------------------------------


def _money_loaded(which: str) -> _Loaded:
    files = _files("money_marketplace")
    names = [
        "app.money", "app.money.settings", "app.money.currency", "app.money.tax",
        "app.money.ledger", "app.money.ledger.models",
        "app.money.invoicing", "app.money.invoicing.config", "app.money.invoicing.rules", "app.money.invoicing.totals",
        "app.money.invoicing.schemas", "app.money.invoicing.models", "app.money.invoicing.posting", "app.money.invoicing.service",
        "app.money.reconciliation", "app.money.reconciliation.config", "app.money.reconciliation.matcher",
        "app.money.reconciliation.schemas", "app.money.reconciliation.models", "app.money.reconciliation.service",
    ]
    del which
    return _Loaded(files, names, _base_stub())


_TENANT = __import__("uuid").uuid4()


def _ns(**kw: Any) -> types.SimpleNamespace:
    return types.SimpleNamespace(**kw)


@pytest.mark.parametrize("n", [1, 7])
def test_list_invoices_runs_a_constant_number_of_statements(n: int) -> None:
    loaded = _money_loaded("invoicing")
    try:
        svc = loaded.mods["app.money.invoicing.service"]
        import uuid

        ids = [uuid.uuid4() for _ in range(n)]
        now = datetime.now(UTC)

        def invoice(i: Any) -> types.SimpleNamespace:
            return _ns(
                id=i, kind="receivable", number="N", status="draft", counterparty="c", counterparty_ref=None, currency="USD",
                issue_date=None, due_date=None, notes=None, subtotal_minor=0, tax_minor=0, total_minor=0, paid_minor=0,
                issue_tx_id=None, void_tx_id=None, created_at=now, issued_at=None, voided_at=None, tenant_id=None,
            )

        def route(sql: str, params: dict[str, Any]) -> list[Any]:
            if "count(" in sql:
                return [n]
            if "FROM invoice_lines" in sql or "FROM invoice_payments" in sql:
                return []
            return [invoice(i) for i in ids]

        session = FakeSession(route)
        import asyncio

        items, total = asyncio.run(svc.list_invoices(session, _ns(tenant_id=_TENANT), 50, 0, None, None, None))
        assert (len(items), total) == (n, n)
        assert len(session.sql) == 4, session.sql  # count, page, lines IN, payments IN: not 2 per invoice
        assert any("invoice_lines.invoice_id IN" in s for s in session.sql) and any("invoice_payments.invoice_id IN" in s for s in session.sql)
    finally:
        loaded.close()


@pytest.mark.parametrize("n", [1, 6])
def test_list_runs_counts_in_two_grouped_queries(n: int) -> None:
    loaded = _money_loaded("reconciliation")
    try:
        svc = loaded.mods["app.money.reconciliation.service"]
        import asyncio
        import uuid

        ids = [uuid.uuid4() for _ in range(n)]
        now = datetime.now(UTC)

        def run(i: Any) -> types.SimpleNamespace:
            return _ns(
                id=i, account_id=uuid.uuid4(), currency="USD", name="r", period_start=None, period_end=None, status="open",
                created_at=now, closed_at=None, summary=None, tenant_id=None,
            )

        def route(sql: str, params: dict[str, Any]) -> list[Any]:
            if "GROUP BY" in sql:
                return [(i, 3) for i in ids] if "reconciliation_lines" in sql else [(ids[0], 1)]
            if "count(" in sql:
                return [n]
            return [run(i) for i in ids]

        session = FakeSession(route)
        items, total = asyncio.run(svc.list_runs(session, _ns(tenant_id=_TENANT), 50, 0, None))
        assert (len(items), total) == (n, n)
        assert len(session.sql) == 4, session.sql  # count, page, lines GROUP BY, matches GROUP BY
        assert all(x.line_count == 3 for x in items) and items[0].matched_count == 1
        assert all(x.matched_count == 0 for x in items[1:])
    finally:
        loaded.close()


def test_results_pages_the_matched_pairs() -> None:
    files = _files("money_marketplace")
    router, service, schemas = (files[f"app/money/reconciliation/{n}.py"] for n in ("router", "service", "schemas"))
    assert "Query(ge=1, le=200)] = 100" in router and "offset: Offset = 0" in router and "matched_total" in schemas
    assert "matched[offset : offset + limit]" in service and "covers every pair" in router


# --- 5B L5: tolerance relative to the currency ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("currencies", "tolerance", "refused"),
    [(["USD"], 10_000, False), (["USD"], 10_001, True), (["JPY"], 100, False), (["JPY"], 101, True), (["USD", "JPY"], 150, True), ([], 10_001, True)],
)
def test_tolerance_is_capped_relative_to_the_currency(currencies: list[str], tolerance: int, refused: bool) -> None:
    raw = _raw("money_ledger")
    raw["packs"]["money"]["reconciliation"] = {"read_roles": ["admin"], "run_roles": ["admin"], "tolerance_minor": tolerance, "max_lines": 50}
    raw["packs"]["money"]["currency"]["currencies"] = currencies
    codes = {i.code for i in validate(Spec.model_validate(raw))}
    assert ("tolerance_too_large" in codes) is refused


# --- booking ---------------------------------------------------------------------------------------------------


def _booking_loaded() -> _Loaded:
    files = _files("booking_clinic")
    names = [
        "app.booking", "app.booking.config", "app.booking.rules", "app.booking.schemas", "app.booking.models", "app.booking.service",
    ]
    stubs = _base_stub()
    stubs["app.auth"] = _stub("app.auth")
    stubs["app.auth.service"] = _stub("app.auth.service", effective_roles=lambda roles: set(roles))
    return _Loaded(files, names, stubs)


@pytest.fixture
def bk() -> Any:
    loaded = _booking_loaded()
    try:
        yield loaded.mods
    finally:
        loaded.close()


def _user(bk: Any, role: str, uid: Any = None) -> types.SimpleNamespace:
    import uuid

    return _ns(id=uid or uuid.uuid4(), roles=[role], tenant_id=uuid.uuid4())


def _row(**kw: Any) -> types.SimpleNamespace:
    import uuid

    base = dict(
        id=uuid.uuid4(), resource_id=uuid.uuid4(), tenant_id=None, status="confirmed", exclusive=True,
        starts_at=datetime.now(UTC) + timedelta(hours=1), ends_at=datetime.now(UTC) + timedelta(hours=2), quantity=1,
        hold_expires_at=None, customer_id=uuid.uuid4(), customer_ref=None, notes=None, idempotency_key=None, request_hash=None,
        cancel_fee_minor=None, fee_currency=None, cancel_reason=None, created_at=datetime.now(UTC), confirmed_at=None,
        cancelled_at=None, expired_at=None,
    )
    base.update(kw)
    return _ns(**base)


def _resource() -> types.SimpleNamespace:
    import uuid

    return _ns(id=uuid.uuid4(), kind="visit", mode="slot", name="Dr", timezone="UTC", slot_minutes=30, schedule={}, capacity=1,
               min_minutes=None, max_minutes=None, active=True, created_at=datetime.now(UTC), tenant_id=None)


def _run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)


def test_replay_of_an_expired_or_cancelled_booking_is_idempotency_key_spent(bk: Any) -> None:
    svc, schemas = bk["app.booking.service"], bk["app.booking.schemas"]
    start = datetime.now(UTC) + timedelta(days=2)
    body = schemas.BookingCreate(resource_id=_resource().id, starts_at=start, idempotency_key="key-1")
    res = _resource()
    res.id = body.resource_id
    for status in ("cancelled", "expired", "confirmed", "held"):
        fp = svc._fingerprint(str(res.id), svc._utc(start).isoformat(), None, body.quantity, body.confirm, body.customer_ref, body.notes)
        existing = _row(status=status, request_hash=fp, hold_expires_at=datetime.now(UTC) + timedelta(minutes=5) if status == "held" else None)

        def route(sql: str, params: dict[str, Any], existing: Any = existing) -> list[Any]:
            if sql.startswith("UPDATE"):
                return []
            return [res] if "FROM booking_resources" in sql else [existing]

        session = FakeSession(route)
        user = _user(bk, "customer")
        if status in ("cancelled", "expired"):
            with pytest.raises(_AppError) as err:
                _run(svc.create_booking(session, user, body))
            assert err.value.code == "idempotency_key_spent" and err.value.status == 409 and "new idempotency_key" in err.value.message
        else:
            out, replayed = _run(svc.create_booking(session, user, body))
            assert replayed is True and out.status == status


def test_reconfirming_a_confirmed_booking_is_a_200_and_expired_or_cancelled_stay_refused(bk: Any) -> None:
    svc = bk["app.booking.service"]
    res = _resource()
    user = _user(bk, "customer")
    for status, code in (("confirmed", None), ("cancelled", "invalid_transition"), ("expired", "hold_expired")):
        row = _row(status=status, customer_id=user.id, resource_id=res.id)
        session = FakeSession(lambda sql, params, row=row: [res] if "FROM booking_resources" in sql else [row])
        if code is None:
            out = _run(svc.confirm_booking(session, user, row.id))
            assert out.status == "confirmed" and session.commits == 0
            assert not [s for s in session.sql if s.startswith("UPDATE")]
        else:
            with pytest.raises(_AppError) as err:
                _run(svc.confirm_booking(session, user, row.id))
            assert err.value.code == code


def _cancel_fee(svc: Any, schemas: Any, user: Any, row: Any, res: Any) -> Any:
    session = FakeSession(lambda sql, params: [res] if "FROM booking_resources" in sql else [row])
    _run(svc.cancel_booking(session, user, row.id, schemas.CancelIn()))
    updates = [p for s, p in zip(session.sql, session.params, strict=True) if s.startswith("UPDATE")]
    assert updates
    return updates[-1]["cancel_fee_minor"]


def test_cancellation_fee_is_zero_for_a_manager_cancelling_someone_elses_booking(bk: Any) -> None:
    svc, schemas = bk["app.booking.service"], bk["app.booking.schemas"]
    res = _resource()
    soon = datetime.now(UTC) + timedelta(minutes=30)  # inside the free window: a fee applies to the customer
    customer = _user(bk, "customer")
    manager = _user(bk, "staff")
    mine = _row(status="confirmed", customer_id=customer.id, resource_id=res.id, starts_at=soon, ends_at=soon + timedelta(hours=1))
    assert _cancel_fee(svc, schemas, customer, mine, res) > 0
    theirs = _row(status="confirmed", customer_id=customer.id, resource_id=res.id, starts_at=soon, ends_at=soon + timedelta(hours=1))
    assert _cancel_fee(svc, schemas, manager, theirs, res) == 0
    own = _row(status="confirmed", customer_id=manager.id, resource_id=res.id, starts_at=soon, ends_at=soon + timedelta(hours=1))
    assert _cancel_fee(svc, schemas, manager, own, res) > 0  # a manager cancelling their own booking pays like anyone
    assert "never charges" in _files("booking_clinic")["app/booking/router.py"]


def test_reads_do_not_sweep_or_commit_and_report_a_stale_hold_as_expired(bk: Any) -> None:
    svc = bk["app.booking.service"]
    res = _resource()
    user = _user(bk, "staff")
    stale = _row(status="held", resource_id=res.id, hold_expires_at=datetime.now(UTC) - timedelta(minutes=1))

    def route(sql: str, params: dict[str, Any]) -> list[Any]:
        if "count(" in sql:
            return [1]
        return [res] if "FROM booking_resources" in sql else [stale]

    session = FakeSession(route)
    items, _ = _run(svc.list_bookings(session, user, 50, 0, None, None, None, None))
    assert session.commits == 0 and not [s for s in session.sql if s.startswith("UPDATE")]
    assert items[0].status == "expired" and items[0].hold_expires_at is None
    session = FakeSession(route)
    one = _run(svc.get_booking(session, user, stale.id))
    assert session.commits == 0 and not [s for s in session.sql if s.startswith("UPDATE")] and one.status == "expired"
    session = FakeSession(route)
    _run(svc.list_bookings(session, user, 50, 0, None, "expired", None, None))
    assert any("hold_expires_at <=" in s for s in session.sql)


def test_only_writes_call_the_sweep() -> None:
    tree = ast.parse(_files("booking_clinic")["app/booking/service.py"])
    callers = {
        fn.name
        for fn in ast.walk(tree)
        if isinstance(fn, ast.AsyncFunctionDef)
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") in {"_lazy_expire", "sweep_expired"}
    }
    assert callers == {"create_booking", "expire_holds", "_lazy_expire"}  # _lazy_expire itself is called only by create_booking (below)
    assert [f.name for f in ast.walk(tree) if isinstance(f, ast.AsyncFunctionDef) and any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_lazy_expire" for n in ast.walk(f))] == ["create_booking"]


def test_the_booking_guard_refuses_bad_inserts_deletes_and_confirmed_row_edits() -> None:
    migration = _files("booking_clinic")["alembic/versions/0037_booking.py"]
    assert "BEFORE INSERT OR UPDATE OR DELETE ON bookings" in migration
    assert "TG_OP = 'DELETE'" in migration and "TG_OP = 'INSERT'" in migration and "NEW.status NOT IN ('held', 'confirmed')" in migration
    assert "NEW.customer_id IS DISTINCT FROM OLD.customer_id" in migration
    assert "NEW.hold_expires_at IS DISTINCT FROM OLD.hold_expires_at" in migration
    assert "NEW.cancel_fee_minor IS DISTINCT FROM OLD.cancel_fee_minor AND NEW.status <> 'cancelled'" in migration
    assert "BEFORE TRUNCATE" not in migration.upper()  # generated tests run TRUNCATE ... CASCADE on the tenant tables
    assert "0038" not in migration
