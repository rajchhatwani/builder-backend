"""Payment security and operations tests (generated): forged webhooks, unsafe settings, secrets in
logs, the audit trail, the job queue, reconciliation and races between concurrent requests."""

import asyncio
import importlib
import json
import threading
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.auth.models import AuthUser
from app.core import redact
from app.db import session_factory
from app.models.orders import Order
from app.payments import audit, config, jobs, money, reconcile, worker
from app.payments.lock import ModeMismatchError, ensure_payments_lock
from app.payments.models import AuditLog, Job, Payment, PaymentsLock, Refund, WebhookEvent
from app.payments.providers import get_provider
from app.payments.providers.base import ProviderError
from app.payments.service import safe_checkout_url
from tests import _factories
from tests._auth_support import client_for, sign_in
from tests.payments_support import (
    DEFAULT_API_BASE,
    ENV,
    ENV_API_BASE,
    ENV_KEY,
    ENV_WEBHOOK_SECRETS,
    LIVE_ENV,
    OTHER_WEBHOOK_SECRET,
    SECRET_VALUES,
    WEBHOOK_PATH,
    WEBHOOK_SECRET,
    FakeProvider,
    live_settings_kwargs,
    settings_kwargs,
    unsafe_settings,
)

pytestmark = pytest.mark.usefixtures("payments_env")

ORDER_FIELDS: dict[str, Any] = {'status': 'pending'}
CUSTOMER = "pay@example.com"
CURRENCY = config.CURRENCIES[0]


def role(key: str) -> list[str]:
    roles = config.ROLES[key]
    if not roles:
        pytest.skip(f"no role may {key} in this project")
    return [roles[0]]


CREATOR_ROLES: tuple[str, ...] = ('admin', 'staff')


async def order_for(
    client: AsyncClient, owner_headers: dict[str, str], owner_email: str, total: str = "19.99", n: int = 0
) -> str:
    """An item that `owner_email` will pay for, created the way this project's roles allow."""
    fields = {**ORDER_FIELDS, "total": total}
    # Payers may not write items (they would set their own price): staff create it ...
    creator = await sign_in(
        client, f"creator-{owner_email}", roles=[CREATOR_ROLES[0]], n=5 + n % 5, join=owner_email
    )
    async with client_for(creator) as staff:
        item_id = str((await _factories.make_orders(staff, **fields))["id"])
    # ... and it belongs to the payer, as an endpoint of your own that creates it for them would do.
    async with session_factory() as session:
        owner_id = (
            await session.execute(select(AuthUser.id).where(AuthUser.email == owner_email))
        ).scalar_one()
        await session.execute(
            sa.update(Order).where(Order.id == uuid.UUID(item_id)).values(created_by_id=owner_id)
        )
        await session.commit()
    return item_id


async def started_payment(
    client: AsyncClient, email: str = CUSTOMER, n: int = 0
) -> tuple[dict[str, str], str, str]:
    headers = await sign_in(client, email, roles=role("create"), n=n)
    order_id = await order_for(client, headers, email, n=n)
    async with client_for(headers) as customer:
        created = await customer.post(
            "/payments",
            json={"payable_id": order_id},
            headers={"Idempotency-Key": f"key-{uuid.uuid4()}"},
        )
    assert created.status_code == 201, created.text
    return headers, order_id, str(created.json()["id"])


async def post_event(client: AsyncClient, body: bytes, headers: dict[str, str], path: str = WEBHOOK_PATH) -> Any:
    return await client.post(path, content=body, headers=headers)


async def deliver(client: AsyncClient, event: tuple[bytes, dict[str, str]] | None) -> Any:
    assert event is not None
    return await post_event(client, *event)


async def count(model: Any) -> int:
    async with session_factory() as session:
        return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


# --- forged and malformed webhooks ---------------------------------------------------------------


async def test_a_correctly_signed_webhook_is_accepted(
    client: AsyncClient, payments_env: FakeProvider
) -> None:
    _, _, payment_id = await started_payment(client)
    sid = payments_env.only_session_id()
    payments_env.pay(sid)
    assert (await deliver(client, payments_env.completed_event(sid))).status_code == 200
    async with session_factory() as session:
        payment = await session.get(Payment, uuid.UUID(payment_id))
    assert payment is not None and payment.status == "succeeded"


async def test_every_kind_of_forgery_gets_the_same_plain_refusal(
    client: AsyncClient, payments_env: FakeProvider
) -> None:
    _, _, payment_id = await started_payment(client)
    sid = payments_env.only_session_id()
    payments_env.pay(sid)
    good_body, _ = payments_env.completed_event(sid)
    answers = set()
    for name, (body, headers) in payments_env.forgeries(good_body).items():
        before = await count(WebhookEvent)
        response = await post_event(client, body, headers)
        assert response.status_code == 400, f"{name}: {response.status_code}"
        answers.add(response.text)
        assert await count(WebhookEvent) == before, f"{name}: stored"
    assert len(answers) == 1, "refusals differ, which would tell an attacker what failed"
    assert "signature" not in next(iter(answers)).lower()
    async with session_factory() as session:
        payment = await session.get(Payment, uuid.UUID(payment_id))
    assert payment is not None and payment.status == "requires_payment", "a forgery changed state"


async def test_a_live_mode_event_is_refused_on_a_test_system(
    client: AsyncClient, payments_env: FakeProvider
) -> None:
    await started_payment(client)
    sid = payments_env.only_session_id()
    payments_env.pay(sid)
    event = payments_env.live_mode_event(sid)
    if event is None:
        pytest.skip("this provider's events do not say whether they are live")
    assert (await deliver(client, event)).status_code == 400
    assert await count(WebhookEvent) == 0


async def test_a_second_signing_secret_lets_the_secret_be_rotated(
    client: AsyncClient, payments_env: FakeProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    await started_payment(client)
    sid = payments_env.only_session_id()
    payments_env.pay(sid)
    body, _ = payments_env.completed_event(sid)
    rotated = payments_env.signed(body, secret=OTHER_WEBHOOK_SECRET)
    assert (await post_event(client, body, rotated)).status_code == 400  # not configured yet
    monkeypatch.setenv(ENV_WEBHOOK_SECRETS, f"{WEBHOOK_SECRET}, {OTHER_WEBHOOK_SECRET}")
    config.get_payments_settings.cache_clear()
    assert (await post_event(client, body, rotated)).status_code == 200


async def test_one_valid_signature_among_several_is_enough(
    client: AsyncClient, payments_env: FakeProvider
) -> None:
    await started_payment(client)
    sid = payments_env.only_session_id()
    payments_env.pay(sid)
    body, _ = payments_env.completed_event(sid)
    headers = payments_env.multi_signature_headers(body)
    if headers is None:
        pytest.skip("this provider sends one signature")
    assert (await post_event(client, body, headers)).status_code == 200


async def test_an_oversized_body_is_refused_before_it_is_read(
    client: AsyncClient, payments_env: FakeProvider
) -> None:
    big = b"x" * (config.WEBHOOK_MAX_BODY_BYTES + 1)
    response = await post_event(client, big, payments_env.signed(big))
    assert response.status_code == 413

    async def chunks() -> Any:
        for _ in range(config.WEBHOOK_MAX_BODY_BYTES // 1024 + 2):
            yield b"x" * 1024

    streamed = await client.post(WEBHOOK_PATH, content=chunks(), headers={"X-Anything": "1"})
    assert streamed.status_code == 413
    assert await count(WebhookEvent) == 0


async def test_only_the_configured_provider_has_a_webhook_route(
    client: AsyncClient, payments_env: FakeProvider
) -> None:
    body, headers = payments_env.ghost_event()
    assert (await post_event(client, body, headers, "/payments/webhooks/paypal")).status_code == 404
    assert (await client.get(WEBHOOK_PATH)).status_code == 405


async def test_the_webhook_ip_allowlist_when_enabled(
    client: AsyncClient, payments_env: FakeProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    await started_payment(client)
    sid = payments_env.only_session_id()
    payments_env.pay(sid)
    event = payments_env.completed_event(sid)
    monkeypatch.setattr(config, "WEBHOOK_IP_ALLOWLIST_ENABLED", True)
    monkeypatch.setenv("PAYMENTS_WEBHOOK_IP_ALLOWLIST", "203.0.113.0/24")
    config.get_payments_settings.cache_clear()
    assert (await deliver(client, event)).status_code == 400  # the test client is 127.0.0.1
    monkeypatch.setenv("PAYMENTS_WEBHOOK_IP_ALLOWLIST", "127.0.0.0/8, 203.0.113.0/24")
    config.get_payments_settings.cache_clear()
    assert (await deliver(client, event)).status_code == 200


async def test_the_webhook_is_not_in_the_public_api_description(client: AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).text
    assert "/payments/webhooks" not in schema
    assert not any(secret in schema for secret in SECRET_VALUES)


# --- settings: unsafe values stop the app --------------------------------------------------------


def settings(**overrides: Any) -> config.PaymentsSettings:
    return config.PaymentsSettings(**settings_kwargs(**overrides))


def test_safe_settings_pass() -> None:
    settings().check()
    config.PaymentsSettings(**live_settings_kwargs()).check()


@pytest.mark.parametrize("overrides", unsafe_settings())
def test_unsafe_settings_are_refused(overrides: dict[str, Any]) -> None:
    with pytest.raises(config.PaymentsConfigError):
        settings(**overrides).check()


@pytest.mark.parametrize(
    "overrides",
    [
        {"payments_webhook_mode": "sometimes"},
        {"payments_worker_concurrency": 0},
        {"payments_poll_interval_seconds": 0},
    ],
)
def test_unsafe_tuning_is_refused(overrides: dict[str, Any]) -> None:
    with pytest.raises(config.PaymentsConfigError):
        settings(**overrides).check()


def test_secrets_never_show_in_a_repr_or_str() -> None:
    shown = repr(settings()) + str(settings()) + str(settings().model_dump())
    assert not any(secret in shown for secret in SECRET_VALUES)


def test_secrets_can_come_from_files_but_not_from_both_places(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not config.SECRETS_FROM_FILES:
        pytest.skip("file-based secrets are switched off for this project")
    key_file = tmp_path / "key"
    key_file.write_text(ENV[ENV_KEY] + "\n")
    monkeypatch.delenv(ENV_KEY)
    monkeypatch.setenv(f"{ENV_KEY}_FILE", str(key_file))
    config.get_payments_settings.cache_clear()
    assert config.get_payments_settings().secret_key() == ENV[ENV_KEY]
    monkeypatch.setenv(ENV_KEY, ENV[ENV_KEY])
    config.get_payments_settings.cache_clear()
    with pytest.raises(config.PaymentsConfigError):
        config.get_payments_settings()
    monkeypatch.delenv(ENV_KEY)
    monkeypatch.setenv(f"{ENV_KEY}_FILE", str(tmp_path / "missing"))
    config.get_payments_settings.cache_clear()
    with pytest.raises(config.PaymentsConfigError):
        config.get_payments_settings()


async def test_test_and_live_payments_never_share_a_database(monkeypatch: pytest.MonkeyPatch) -> None:
    async with session_factory() as session:
        await session.execute(sa.delete(PaymentsLock))
        await session.commit()
    try:
        await ensure_payments_lock()  # records test mode
        await ensure_payments_lock()  # the same mode again is fine
        for name, value in LIVE_ENV.items():
            monkeypatch.setenv(name, value)
        monkeypatch.setenv(ENV_API_BASE, DEFAULT_API_BASE)
        monkeypatch.setenv("APP_ENV", "production")
        config.get_payments_settings.cache_clear()
        with pytest.raises(ModeMismatchError):
            await ensure_payments_lock()
        monkeypatch.setenv("PAYMENTS_ALLOW_MODE_SWITCH", "true")
        config.get_payments_settings.cache_clear()
        await ensure_payments_lock()
        async with session_factory() as session:
            lock = await session.get(PaymentsLock, 1)
            assert lock is not None and lock.livemode is True
    finally:
        async with session_factory() as session:
            await session.execute(sa.delete(PaymentsLock))
            await session.commit()


# --- secrets in logs and responses -----------------------------------------------------------------


def test_the_log_filter_hides_secrets() -> None:
    samples = [
        "sk_test_" + "a" * 24,
        "whsec_" + "b" * 32,
        "Bearer abcdefghijklmnop",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk",
        "t=1700000000,v1=" + "a" * 64,
        "postgresql://user:hunter2@db:5432/app",
        "rzp_live_" + "AbCdEf123456",
    ]
    for sample in samples:
        cleaned = redact.scrub_text(f"value {sample} end")
        assert redact.REDACTED in cleaned, sample
    assert "hunter2" not in redact.scrub_text(samples[5])
    scrubbed = redact.scrub(
        {"password": "x", "nested": {"api_key": "y", "ok": "fine"}, "list": ["sk_test_" + "a" * 24]}
    )
    assert scrubbed == {"password": "[redacted]", "nested": {"api_key": "[redacted]", "ok": "fine"}, "list": ["[redacted]"]}


def test_the_configured_secrets_are_hidden_wherever_they_appear() -> None:
    """Secrets without a recognisable shape (some providers use plain strings) are known by value."""
    config.get_payments_settings()
    for secret in SECRET_VALUES[:2]:
        assert secret not in redact.scrub_text(f"error talking to the provider with {secret}")


async def test_no_secret_reaches_the_logs_or_the_responses(
    client: AsyncClient, payments_env: FakeProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    headers = await sign_in(client, CUSTOMER, roles=role("create"))
    order_id = await order_for(client, headers, CUSTOMER)
    async with client_for(headers) as customer:
        payments_env.rejection("card_declined", f"bad key {SECRET_VALUES[0]}")
        failed = await customer.post(
            "/payments", json={"payable_id": order_id}, headers={"Idempotency-Key": "key-aaaaaaaa"}
        )
        ok = await customer.post(
            "/payments", json={"payable_id": order_id}, headers={"Idempotency-Key": "key-bbbbbbbb"}
        )
    body, _ = payments_env.ghost_event()
    bad = payments_env.signed(body, secret=OTHER_WEBHOOK_SECRET)
    refused = await post_event(client, body, bad)
    out = capsys.readouterr()
    everything = out.out + out.err + failed.text + ok.text + refused.text
    for secret in (*SECRET_VALUES, *[v for v in bad.values() if len(v) > 40]):
        assert secret not in everything
    assert "Bearer sk_" not in everything


async def test_the_provider_client_never_follows_a_redirect(
    payments_env: FakeProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    """urllib would send our credentials to wherever a redirect points; it must refuse instead."""
    hits: list[str] = []

    class Target(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

    target = ThreadingHTTPServer(("127.0.0.1", 0), Target)
    threading.Thread(target=target.serve_forever, daemon=True).start()
    target_url = f"http://127.0.0.1:{target.server_address[1]}/stolen"

    class Redirector(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(302)
            self.send_header("Location", target_url)
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

    redirector = ThreadingHTTPServer(("127.0.0.1", 0), Redirector)
    threading.Thread(target=redirector.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv(ENV_API_BASE, f"http://127.0.0.1:{redirector.server_address[1]}")
        config.get_payments_settings.cache_clear()
        with pytest.raises(ProviderError):
            await get_provider().retrieve_checkout("cs_test_1")
    finally:
        redirector.shutdown()
        target.shutdown()
    assert hits == [], "the redirect was followed"
    module = importlib.import_module(f"app.payments.providers.{config.PROVIDER}")
    assert module._NoRedirect().redirect_request(None, None, 302, "Found", {}, target_url) is None


def test_the_page_the_payer_is_sent_to_must_be_https_in_production() -> None:
    assert safe_checkout_url("https://pay.example.com/c/1", production=True)
    assert not safe_checkout_url("http://pay.example.com/c/1", production=True)
    assert not safe_checkout_url("javascript:alert(1)", production=True)
    assert not safe_checkout_url("", production=False)
    assert not safe_checkout_url(None, production=False)
    assert safe_checkout_url("http://127.0.0.1:9000/c/1", production=False)


# --- the audit trail ------------------------------------------------------------------------------


async def test_the_audit_trail_cannot_be_edited_deleted_or_emptied(
    client: AsyncClient, payments_env: FakeProvider
) -> None:
    _, _, payment_id = await started_payment(client)
    async with session_factory() as session:
        for statement in (
            "UPDATE pay_audit_log SET event = 'x'",
            "DELETE FROM pay_audit_log",
            "TRUNCATE pay_audit_log",
        ):
            with pytest.raises(DBAPIError):
                await session.execute(sa.text(statement))
            await session.rollback()
        entries = (
            await session.execute(
                select(func.count()).select_from(AuditLog).where(AuditLog.chain_key == payment_id)
            )
        ).scalar_one()
    assert entries >= 2  # payment_created, checkout_created


async def test_a_tampered_trail_is_detected(client: AsyncClient, payments_env: FakeProvider) -> None:
    _, _, payment_id = await started_payment(client)
    async with session_factory() as session:
        assert await audit.verify_chain(session, uuid.UUID(payment_id)) == (True, None)
    # Only someone who owns the table can switch the protection off; the chain still gives them away.
    async with session_factory() as session:
        await session.execute(sa.text("ALTER TABLE pay_audit_log DISABLE TRIGGER pay_audit_append_only"))
        await session.execute(
            sa.text("UPDATE pay_audit_log SET data = '{\"amount_minor\": 1}'::jsonb WHERE chain_key = :k AND seq = 1"),
            {"k": payment_id},
        )
        await session.commit()
    try:
        async with session_factory() as session:
            assert await audit.verify_chain(session, uuid.UUID(payment_id)) == (False, 1)
    finally:
        async with session_factory() as session:
            await session.execute(sa.text("DELETE FROM pay_audit_log WHERE chain_key = :k"), {"k": payment_id})
            await session.execute(sa.text("ALTER TABLE pay_audit_log ENABLE TRIGGER pay_audit_append_only"))
            await session.commit()


async def test_audit_entries_never_hold_secrets() -> None:
    async with session_factory() as session:
        entry = await audit.append(
            session,
            payment_id=None,
            event="probe",
            data={"api_key": SECRET_VALUES[0], "note": "sk_test_" + "a" * 24},
        )
        await session.commit()
    assert SECRET_VALUES[0] not in json.dumps(entry.data)
    assert ("sk_test_" + "a" * 24) not in json.dumps(entry.data)


async def test_operators_can_verify_the_trail_and_nobody_else(
    client: AsyncClient, payments_env: FakeProvider
) -> None:
    _, _, payment_id = await started_payment(client)
    operator = await sign_in(client, "ops@example.com", roles=role("operate"), n=1, join=CUSTOMER)
    async with client_for(operator) as http:
        verdict = await http.get(f"/payments/ops/audit/{payment_id}/verify")
        status = await http.get("/payments/ops/status")
    assert verdict.status_code == 200 and verdict.json() == {"intact": True, "first_bad_sequence": None}
    assert status.status_code == 200 and "queue" in status.json()
    allowed = set(config.ROLES["operate"])
    outsider_roles = [r for r in ('admin', 'staff', 'customer') if r not in allowed]
    if outsider_roles:
        outsider = await sign_in(client, "out@example.com", roles=outsider_roles[:1], n=2, join=CUSTOMER)
        async with client_for(outsider) as http:
            for path in (
                "/payments/ops/status",
                "/payments/ops/dead-jobs",
                f"/payments/ops/audit/{payment_id}/verify",
            ):
                assert (await http.get(path)).status_code == 403


# --- money ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "minor"),
    [("19.99", 1999), ("0.01", 1), ("5", 500), (Decimal("1E+3"), 100000), ("12.30", 1230), (7, 700)],
)
def test_exact_amounts_convert(amount: object, minor: int) -> None:
    assert money.to_minor(amount, CURRENCY) == minor


@pytest.mark.parametrize("amount", ["19.999", "0.001", "0", "-1", "NaN", "Infinity", "abc", "", None])
def test_inexact_or_invalid_amounts_are_refused_never_rounded(amount: object) -> None:
    with pytest.raises(Exception) as caught:  # noqa: PT011 - AppError, checked below
        money.to_minor(amount, CURRENCY)
    assert getattr(caught.value, "status_code", None) == 422


def test_amount_limits_and_currencies() -> None:
    assert money.to_minor(Decimal(config.MAX_AMOUNT_MINOR) / 100, CURRENCY) == config.MAX_AMOUNT_MINOR
    with pytest.raises(Exception) as too_big:  # noqa: PT011
        money.to_minor(Decimal(config.MAX_AMOUNT_MINOR + 1) / 100, CURRENCY)
    assert too_big.value.status_code == 422  # type: ignore[attr-defined]
    with pytest.raises(Exception) as unknown:  # noqa: PT011
        money.to_minor("1.00", "XXX")
    assert unknown.value.code == "currency_not_allowed"  # type: ignore[attr-defined]
    assert money.normalise_currency(f" {CURRENCY.lower()} ") == CURRENCY


def test_a_currency_without_minor_units_takes_whole_numbers_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(config.EXPONENTS, "JPY", 0)
    assert money.to_minor("500", "JPY") == 500
    with pytest.raises(Exception) as caught:  # noqa: PT011
        money.to_minor("500.5", "JPY")
    assert caught.value.code == "amount_not_representable"  # type: ignore[attr-defined]
    assert money.to_major(500, "JPY") == Decimal(500)


# --- the job queue --------------------------------------------------------------------------------


async def test_a_job_is_run_by_one_worker_even_when_many_ask_at_once() -> None:
    async with session_factory() as session:
        await jobs.enqueue(session, jobs.RECONCILE, {})
        await session.commit()

    async def ask(name: str) -> int:
        async with session_factory() as session:
            claimed = await jobs.claim(session, worker_id=name, limit=5, lease_seconds=60)
            await session.commit()
            return len(claimed)

    results = await asyncio.gather(*[ask(f"w{i}") for i in range(8)])
    assert sum(results) == 1


async def test_a_worker_never_waits_for_a_job_another_worker_is_holding() -> None:
    """The claim skips rows another claimer has locked instead of queueing behind them, so a slow
    worker cannot stall the others."""
    async with session_factory() as session:
        await jobs.enqueue(session, jobs.RECONCILE, {})
        await session.commit()
    holder = session_factory()
    async with holder as holding:
        await holding.execute(sa.text("SELECT id FROM pay_jobs FOR UPDATE"))  # lock held, not committed

        async def claim_meanwhile() -> list[jobs.ClaimedJob]:
            async with session_factory() as other:
                claimed = await jobs.claim(other, worker_id="other", limit=5, lease_seconds=60)
                await other.commit()
                return claimed

        assert await asyncio.wait_for(claim_meanwhile(), timeout=5) == []
        await holding.rollback()


async def test_enqueue_with_a_dedupe_key_creates_one_job() -> None:
    async with session_factory() as session:
        first = await jobs.enqueue(session, jobs.RECONCILE, {}, dedupe_key="same")
        second = await jobs.enqueue(session, jobs.RECONCILE, {}, dedupe_key="same")
        await session.commit()
    assert first is not None and second is None


async def test_a_job_whose_worker_died_is_taken_over_after_the_lease() -> None:
    async with session_factory() as session:
        await jobs.enqueue(session, jobs.RECONCILE, {})
        crashed = await jobs.claim(session, worker_id="crashed", limit=1, lease_seconds=60)
        await session.commit()
        assert len(crashed) == 1
        assert await jobs.claim(session, worker_id="other", limit=1, lease_seconds=60) == []
        await session.execute(sa.update(Job).values(locked_until=datetime.now(UTC) - timedelta(seconds=1)))
        await session.commit()
        taken = await jobs.claim(session, worker_id="other", limit=1, lease_seconds=60)
        await session.commit()
    assert len(taken) == 1 and taken[0].attempts == 2


async def test_failing_jobs_back_off_and_are_dead_lettered() -> None:
    async with session_factory() as session:
        await jobs.enqueue(session, jobs.RECONCILE, {}, max_attempts=2)
        await session.commit()
    for attempt in (1, 2):
        async with session_factory() as session:
            await session.execute(sa.update(Job).where(Job.status == jobs.QUEUED).values(run_at=datetime.now(UTC)))
            claimed = (await jobs.claim(session, worker_id="w", limit=1, lease_seconds=60))[0]
            dead = await jobs.fail(session, claimed, "boom")
            await session.commit()
        assert dead is (attempt == 2)
    async with session_factory() as session:
        job = (await session.execute(select(Job))).scalar_one()
        assert job.status == jobs.DEAD and job.last_error_code == "boom"
        assert await jobs.retry_dead(session, job.id) is True
        await session.commit()
    assert 2.5 <= jobs.backoff_seconds(1) <= 7.5
    assert jobs.backoff_seconds(30) <= 3600 * 1.5


async def test_the_worker_dead_letters_and_operators_can_retry(client: AsyncClient) -> None:
    async with session_factory() as session:
        await jobs.enqueue(session, "no_such_job_type", {}, max_attempts=1)
        await session.commit()
    assert await worker.run_once() == 1
    operator = await sign_in(client, "ops@example.com", roles=role("operate"))
    async with client_for(operator) as http:
        dead = (await http.get("/payments/ops/dead-jobs")).json()
        assert len(dead) == 1 and dead[0]["type"] == "no_such_job_type"
        retried = await http.post(f"/payments/ops/dead-jobs/{dead[0]['id']}/retry")
        assert retried.status_code == 202
        assert (await http.post(f"/payments/ops/dead-jobs/{uuid.uuid4()}/retry")).status_code == 404
    async with session_factory() as session:
        recorded = (
            await session.execute(select(AuditLog.event).where(AuditLog.chain_key == audit.SYSTEM_CHAIN))
        ).scalars().all()
    assert "job_dead" in recorded and "dead_job_retried" in recorded


async def test_periodic_jobs_are_enqueued_once_per_time_bucket() -> None:
    moment = datetime(2030, 1, 1, 12, 0, 5, tzinfo=UTC)
    await worker.schedule_periodic(moment)
    await worker.schedule_periodic(moment)  # every worker calls this; only one set of jobs appears
    await worker.schedule_periodic(moment + timedelta(seconds=61))
    async with session_factory() as session:
        types = sorted((await session.execute(select(Job.type))).scalars().all())
    assert types.count(jobs.RECONCILE) == 2
    assert types.count(jobs.RETENTION) == 1 and types.count(jobs.AUDIT_DIGEST) == 1


async def test_queued_mode_stores_the_event_and_a_worker_applies_it(
    client: AsyncClient, payments_env: FakeProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PAYMENTS_WEBHOOK_MODE", "queued")
    config.get_payments_settings.cache_clear()
    _, _, payment_id = await started_payment(client)
    sid = payments_env.only_session_id()
    payments_env.pay(sid)
    assert (await deliver(client, payments_env.completed_event(sid))).status_code == 200
    async with session_factory() as session:
        payment = await session.get(Payment, uuid.UUID(payment_id))
        event = (await session.execute(select(WebhookEvent))).scalar_one()
    assert payment is not None and payment.status == "requires_payment" and event.status == "received"
    assert await worker.run_once() >= 1
    async with session_factory() as session:
        payment = await session.get(Payment, uuid.UUID(payment_id))
        event = (await session.execute(select(WebhookEvent))).scalar_one()
    assert payment is not None and payment.status == "succeeded" and event.status == "processed"


# --- reconciliation -------------------------------------------------------------------------------


async def age(payment_id: str, minutes: int = 30) -> None:
    async with session_factory() as session:
        past = datetime.now(UTC) - timedelta(minutes=minutes)
        await session.execute(
            sa.update(Payment).where(Payment.id == uuid.UUID(payment_id)).values(updated_at=past, last_synced_at=None)
        )
        await session.commit()


async def test_reconcile_finds_a_payment_whose_webhook_was_lost(
    client: AsyncClient, payments_env: FakeProvider
) -> None:
    _, order_id, payment_id = await started_payment(client)
    payments_env.pay(payments_env.only_session_id())  # paid, but no webhook ever arrived
    await age(payment_id)
    await reconcile.run()
    async with session_factory() as session:
        payment = await session.get(Payment, uuid.UUID(payment_id))
        status = (await session.execute(select(Order.status))).scalar_one()
    assert payment is not None and payment.status == "succeeded"
    assert status == "paid"


async def test_reconcile_picks_up_an_expired_checkout(
    client: AsyncClient, payments_env: FakeProvider
) -> None:
    _, _, payment_id = await started_payment(client)
    payments_env.expire(payments_env.only_session_id())
    await age(payment_id)
    await reconcile.run()
    async with session_factory() as session:
        payment = await session.get(Payment, uuid.UUID(payment_id))
    assert payment is not None and payment.status == "expired"


async def test_reconcile_records_a_refund_made_outside_the_system(
    client: AsyncClient, payments_env: FakeProvider
) -> None:
    _, _, payment_id = await started_payment(client)
    sid = payments_env.only_session_id()
    payments_env.pay(sid)
    await age(payment_id)
    await reconcile.run()  # marks it succeeded
    payments_env.dashboard_refund(payments_env.intent_of(sid), 300)
    async with session_factory() as session:
        await session.execute(sa.update(Payment).values(last_synced_at=datetime.now(UTC) - timedelta(days=1)))
        await session.commit()
    await reconcile.run()
    async with session_factory() as session:
        payment = await session.get(Payment, uuid.UUID(payment_id))
        refund = (await session.execute(select(Refund))).scalar_one()
    assert payment is not None and payment.refunded_minor == 300
    assert refund.source == "provider"


async def test_reconcile_gives_up_on_a_payment_that_never_got_its_checkout(
    client: AsyncClient, payments_env: FakeProvider
) -> None:
    headers = await sign_in(client, CUSTOMER, roles=role("create"))
    order_id = await order_for(client, headers, CUSTOMER)
    async with client_for(headers) as customer:
        payments_env.outage(3)
        first = await customer.post(
            "/payments", json={"payable_id": order_id}, headers={"Idempotency-Key": "key-aaaaaaaa"}
        )
        assert first.status_code == 502
    async with session_factory() as session:
        await session.execute(sa.update(Payment).values(created_at=datetime.now(UTC) - timedelta(minutes=10)))
        await session.commit()
    await reconcile.run()
    async with session_factory() as session:
        payment = (await session.execute(select(Payment))).scalar_one()
    assert payment.status == "failed" and payment.failure_code == "creation_timeout"
    async with client_for(headers) as customer:  # the item is free again
        retry = await customer.post(
            "/payments", json={"payable_id": order_id}, headers={"Idempotency-Key": "key-bbbbbbbb"}
        )
    assert retry.status_code == 201


async def test_retention_removes_only_what_is_safe_to_remove(
    client: AsyncClient, payments_env: FakeProvider
) -> None:
    _, _, payment_id = await started_payment(client)
    sid = payments_env.only_session_id()
    payments_env.pay(sid)
    await deliver(client, payments_env.completed_event(sid))
    async with session_factory() as session:
        await session.execute(sa.update(WebhookEvent).values(received_at=datetime.now(UTC) - timedelta(days=4000)))
        await session.execute(sa.update(Job).values(status=jobs.DONE, updated_at=datetime.now(UTC) - timedelta(days=4000)))
        await session.commit()
    await worker.run_retention()
    assert await count(WebhookEvent) == 0
    assert await count(Payment) == 1
    async with session_factory() as session:
        assert (await audit.verify_chain(session, uuid.UUID(payment_id)))[0] is True


# --- concurrency ----------------------------------------------------------------------------------


async def test_parallel_identical_requests_make_one_payment(
    client: AsyncClient, payments_env: FakeProvider
) -> None:
    headers = await sign_in(client, CUSTOMER, roles=role("create"))
    order_id = await order_for(client, headers, CUSTOMER)
    async with client_for(headers) as customer:

        async def attempt() -> Any:
            return await customer.post(
                "/payments", json={"payable_id": order_id}, headers={"Idempotency-Key": "same-key-123456"}
            )

        results = await asyncio.gather(*[attempt() for _ in range(6)])
    assert {r.status_code for r in results} == {201}, [r.text for r in results]
    assert len({r.json()["id"] for r in results}) == 1
    assert await count(Payment) == 1
    assert len(payments_env.sessions) == 1


async def test_parallel_requests_with_different_keys_charge_the_item_once(
    client: AsyncClient, payments_env: FakeProvider
) -> None:
    headers = await sign_in(client, CUSTOMER, roles=role("create"))
    order_id = await order_for(client, headers, CUSTOMER)
    async with client_for(headers) as customer:

        async def attempt(i: int) -> Any:
            return await customer.post(
                "/payments", json={"payable_id": order_id}, headers={"Idempotency-Key": f"key-{i:08d}"}
            )

        results = await asyncio.gather(*[attempt(i) for i in range(6)])
    codes = sorted(r.status_code for r in results)
    assert codes == [201] + [409] * 5, codes
    assert len(payments_env.sessions) == 1


async def test_the_same_event_delivered_in_parallel_is_applied_once(
    client: AsyncClient, payments_env: FakeProvider
) -> None:
    _, _, payment_id = await started_payment(client)
    sid = payments_env.only_session_id()
    payments_env.pay(sid)
    event = payments_env.completed_event(sid)
    results = await asyncio.gather(*[deliver(client, event) for _ in range(8)])
    assert {r.status_code for r in results} <= {200, 503}
    for _ in range(3):  # a delivery that lost the race may ask for a retry; the provider would
        await deliver(client, event)
    async with session_factory() as session:
        applied = (
            await session.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.chain_key == payment_id, AuditLog.event == "payment_succeeded")
            )
        ).scalar_one()
        payment = await session.get(Payment, uuid.UUID(payment_id))
    assert applied == 1 and payment is not None and payment.status == "succeeded"
    assert await count(WebhookEvent) == 1


async def test_parallel_refunds_cannot_exceed_the_payment(
    client: AsyncClient, payments_env: FakeProvider
) -> None:
    _, _, payment_id = await started_payment(client)
    sid = payments_env.only_session_id()
    payments_env.pay(sid)
    await deliver(client, payments_env.completed_event(sid))
    staff = await sign_in(client, "staff@example.com", roles=role("refund"), n=1, join=CUSTOMER)
    async with client_for(staff) as http:

        async def attempt(i: int) -> Any:
            return await http.post(
                f"/payments/{payment_id}/refunds",
                json={"amount_minor": 1500},
                headers={"Idempotency-Key": f"refund-{i:08d}"},
            )

        results = await asyncio.gather(*[attempt(i) for i in range(5)])
    codes = sorted(r.status_code for r in results)
    assert codes.count(201) == 1 and codes.count(422) == 4, codes
    assert sum(r["amount"] for r in payments_env.refunds.values()) == 1500
