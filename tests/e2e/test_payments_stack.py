"""Payments end to end: generate a payments project, `docker compose up` the real stack (API,
two payments workers, PgBouncer, PostgreSQL and a stand-in for the Stripe API) and drive it over
HTTP the way Stripe and a customer would.

Proves what in-process tests cannot: that webhooks received by one process are applied exactly
once by another, that a worker killed in the middle of a job loses nothing, that the generated
database-roles script and container hardening really work, that PgBouncer in transaction mode is
compatible with the code, and that unsafe configuration stops a container before it moves money.
The stand-in follows the Stripe behaviour the code relies on; it is not Stripe (see DEPLOYMENT.md).
Skipped when `docker compose` is unavailable.
"""

import hashlib
import hmac
import json
import secrets
import shutil
import socket
import subprocess
import time
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.generator import generate
from app.core.spec_models import Spec

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"
PASSWORD = "Correct-horse-battery-1"
SECRET_KEY = "sk_test_" + secrets.token_hex(16)
WEBHOOK_SECRET = "whsec_" + secrets.token_hex(16)
LEASE_SECONDS = 6


def docker_compose_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "compose", "version"], capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(
    not docker_compose_available(), reason="docker compose is not available"
)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class Stack:
    root: Path
    project: str
    api: str
    fake: str

    def compose(
        self, *args: str, timeout: int = 900, stdin: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", "compose", "-p", self.project, *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=stdin,
        )

    def sql(self, statement: str) -> str:
        result = self.compose(
            "exec", "-T", "db", "psql", "-U", "app", "-d", "app", "-At", "-c", statement
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()


def stack_spec() -> dict[str, Any]:
    spec: dict[str, Any] = json.loads(
        (FIXTURES / "payments_stripe.json").read_text(encoding="utf-8")
    )
    # No mail server in this stack: sign-up needs no email confirmation.
    spec["auth"]["registration"] = {"email_verification_required": False}
    spec["auth"]["password_reset"] = {"email_magic_link": False}
    spec["auth"]["smtp"] = None
    spec["auth"]["app_url"] = None
    spec["payments"]["scale"] = {
        "profile": "medium",
        "availability": "ha",
        "db_max_connections": 100,
        "pgbouncer": True,
        "webhook_mode": "queued",
    }
    return spec


OVERRIDE = """\
services:
  fake-stripe:
    build: .
    command: ["python", "-m", "tests.fake_stripe", "12111", "0.0.0.0"]
    environment:
      FAKE_STRIPE_SECRET_KEY: ${STRIPE_SECRET_KEY}
    ports:
      - "${FAKE_PORT}:12111"
  api:
    depends_on:
      fake-stripe:
        condition: service_started
  payments-worker:
    depends_on:
      fake-stripe:
        condition: service_started
"""


@pytest.fixture(scope="module")
def stack(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    root = tmp_path_factory.mktemp("paystack")
    for path, content in generate(Spec.model_validate(stack_spec())).items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    api_port, fake_port = free_port(), free_port()
    (root / "docker-compose.override.yml").write_text(OVERRIDE, encoding="utf-8")
    (root / ".env").write_text(
        "\n".join(
            [
                f"API_PORT={api_port}",
                f"FAKE_PORT={fake_port}",
                "AUTH_JWT_SECRET=" + secrets.token_hex(32),
                f"STRIPE_SECRET_KEY={SECRET_KEY}",
                f"STRIPE_WEBHOOK_SECRETS={WEBHOOK_SECRET}",
                "STRIPE_API_BASE=http://fake-stripe:12111",
                f"PAYMENTS_JOB_LEASE_SECONDS={LEASE_SECONDS}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    running = Stack(
        root=root,
        project=f"paystack{secrets.token_hex(3)}",
        api=f"http://localhost:{api_port}",
        fake=f"http://localhost:{fake_port}",
    )
    try:
        up = running.compose("up", "-d", "--build", "--wait", "--wait-timeout", "600")
        if up.returncode != 0:
            logs = running.compose("logs", "--tail", "80").stdout
            raise AssertionError(f"compose up failed:\n{up.stdout}\n{up.stderr}\n{logs}")
        wait_for(lambda: httpx.get(running.fake + "/_fake/state").status_code == 200, 30)
        yield running
    finally:
        running.compose("down", "-v", "--remove-orphans")


def wait_for(check: Callable[[], bool], seconds: float, what: str = "condition") -> None:
    deadline = time.time() + seconds
    last: Exception | None = None
    while time.time() < deadline:
        try:
            if check():
                return
        except (httpx.HTTPError, AssertionError, KeyError) as exc:
            last = exc
        time.sleep(0.5)
    raise AssertionError(f"timed out waiting for {what}: {last}")


# --- helpers that behave like the outside world ---------------------------------------------


def fake(stack: Stack, action: str, target: str = "", **query: Any) -> dict[str, Any]:
    response = httpx.post(f"{stack.fake}/_fake/{action}/{target}".rstrip("/"), params=query)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def signed_event(event_type: str, obj: dict[str, Any]) -> tuple[bytes, dict[str, str]]:
    """A webhook signed the way Stripe signs it."""
    body = json.dumps(
        {
            "id": f"evt_test_{uuid.uuid4().hex[:20]}",
            "object": "event",
            "api_version": "2024-06-20",
            "created": int(time.time()),
            "livemode": False,
            "type": event_type,
            "data": {"object": obj},
        }
    ).encode()
    stamp = int(time.time())
    digest = hmac.new(WEBHOOK_SECRET.encode(), f"{stamp}.".encode() + body, hashlib.sha256)
    return body, {"Stripe-Signature": f"t={stamp},v1={digest.hexdigest()}"}


@dataclass
class Customer:
    stack: Stack
    headers: dict[str, str]
    email: str = ""

    def http(self) -> httpx.Client:
        return httpx.Client(base_url=self.stack.api, headers=self.headers, timeout=30)


def register(stack: Stack, email: str, roles: list[str] | None = None) -> Customer:
    with httpx.Client(base_url=stack.api, timeout=30) as http:
        created = http.post("/auth/register", json={"email": email, "password": PASSWORD})
        assert created.status_code == 201, created.text
        if roles is not None:
            stack.sql(f"UPDATE auth_users SET roles = '{json.dumps(roles)}'::jsonb WHERE email = '{email}'")
        login = http.post("/auth/login", json={"email": email, "password": PASSWORD})
        assert login.status_code == 200, login.text
        return Customer(stack, {"Authorization": f"Bearer {login.json()['access_token']}"}, email)


_STAFF: dict[str, Customer] = {}


def new_order(customer: Customer, total: str = "19.99") -> str:
    """Staff create the order and it belongs to the payer: payers cannot create or edit orders
    themselves, or they could set their own price."""
    stack = customer.stack
    staff = _STAFF.get(stack.project) or register(stack, "staff@example.com", roles=["staff"])
    _STAFF[stack.project] = staff
    with staff.http() as http:
        created = http.post("/orders", json={"total": total, "status": "pending"})
        assert created.status_code == 201, created.text
        order_id = str(created.json()["id"])
    stack.sql(
        f"UPDATE orders SET created_by_id = (SELECT id FROM auth_users WHERE email = '{customer.email}') "
        f"WHERE id = '{order_id}'"
    )
    with customer.http() as http:  # the payer can read it, but not change it
        assert http.get(f"/orders/{order_id}").status_code == 200
        assert http.patch(f"/orders/{order_id}", json={"total": "0.01"}).status_code == 403
    return order_id


def start_payment(customer: Customer, order_id: str) -> httpx.Response:
    with customer.http() as http:
        return http.post(
            "/payments",
            json={"payable_id": order_id},
            headers={"Idempotency-Key": f"key-{uuid.uuid4()}"},
        )


def payment_status(customer: Customer, payment_id: str) -> str:
    with customer.http() as http:
        return str(http.get(f"/payments/{payment_id}").json()["status"])


def pay_at_provider(stack: Stack, payment_id: str) -> dict[str, Any]:
    session_id = next(
        s["id"]
        for s in fake(stack, "state")["sessions"]
        if s["client_reference_id"] == payment_id
    )
    return fake(stack, "pay", session_id)


# --- the tests ---------------------------------------------------------------------------------


def test_the_stack_runs_pgbouncer_and_two_workers(stack: Stack) -> None:
    ps = stack.compose("ps", "--format", "json", "--status", "running").stdout
    containers = [json.loads(line) for line in ps.splitlines() if line.strip()]
    services = [c["Service"] for c in containers]
    assert services.count("payments-worker") == 2
    assert {"api", "db", "pgbouncer", "fake-stripe"} <= set(services)


def test_a_payment_travels_through_the_queue_to_the_database(stack: Stack) -> None:
    customer = register(stack, "pay1@example.com")
    order_id = new_order(customer)
    created = start_payment(customer, order_id)
    assert created.status_code == 201, created.text
    payment = created.json()
    assert payment["status"] == "requires_payment" and payment["amount_minor"] == 1999

    body, headers = signed_event("checkout.session.completed", pay_at_provider(stack, payment["id"]))
    received = httpx.post(f"{stack.api}/payments/webhooks/stripe", content=body, headers=headers)
    assert received.status_code == 200  # queued: acknowledged at once
    wait_for(lambda: payment_status(customer, payment["id"]) == "succeeded", 40, "the workers")

    assert stack.sql(f"SELECT status FROM orders WHERE id = '{order_id}'") == "paid"
    assert stack.sql("SELECT count(*) FROM pay_jobs WHERE status = 'dead'") == "0"
    with customer.http() as http:
        assert http.get(f"/payments/{payment['id']}").json()["checkout_url"] is None


def test_the_same_event_delivered_to_all_replicas_at_once_is_applied_once(stack: Stack) -> None:
    customer = register(stack, "pay2@example.com")
    payment = start_payment(customer, new_order(customer)).json()
    body, headers = signed_event("checkout.session.completed", pay_at_provider(stack, payment["id"]))

    def deliver(_: int) -> int:
        return httpx.post(f"{stack.api}/payments/webhooks/stripe", content=body, headers=headers).status_code

    with ThreadPoolExecutor(max_workers=16) as pool:
        codes = list(pool.map(deliver, range(48)))
    assert set(codes) == {200}
    wait_for(lambda: payment_status(customer, payment["id"]) == "succeeded", 40, "the workers")
    time.sleep(2)  # a duplicate job, had one been created, would have run by now
    assert stack.sql(f"SELECT count(*) FROM pay_audit_log WHERE chain_key = '{payment['id']}' AND event = 'payment_succeeded'") == "1"
    assert stack.sql("SELECT count(*) FROM pay_webhook_events WHERE payload->>'id' = '" + json.loads(body)["id"] + "'") == "1"


def test_forged_webhooks_get_one_plain_refusal(stack: Stack) -> None:
    body, headers = signed_event("checkout.session.completed", {"id": "cs_x", "object": "checkout.session"})
    answers = {
        httpx.post(f"{stack.api}/payments/webhooks/stripe", content=body + b" ", headers=headers).text,
        httpx.post(f"{stack.api}/payments/webhooks/stripe", content=body).text,
        httpx.post(f"{stack.api}/payments/webhooks/stripe", content=body, headers={"Stripe-Signature": "t=1,v1=" + "0" * 64}).text,
    }
    assert len(answers) == 1 and "invalid_webhook" in answers.pop()


def test_workers_killed_in_the_middle_of_a_job_lose_nothing(stack: Stack) -> None:
    customer = register(stack, "pay3@example.com")
    payment = start_payment(customer, new_order(customer)).json()
    body, headers = signed_event("checkout.session.completed", pay_at_provider(stack, payment["id"]))

    fake(stack, "delay", seconds=20)  # every provider answer now takes 20 s
    assert httpx.post(f"{stack.api}/payments/webhooks/stripe", content=body, headers=headers).status_code == 200
    wait_for(
        lambda: stack.sql("SELECT count(*) FROM pay_jobs WHERE status = 'running'") != "0",
        30,
        "a worker to pick the job up",
    )
    killed = stack.compose("kill", "-s", "SIGKILL", "payments-worker")  # no chance to clean up
    assert killed.returncode == 0, killed.stderr
    assert payment_status(customer, payment["id"]) == "requires_payment"

    fake(stack, "delay", seconds=0)
    restarted = stack.compose("up", "-d", "--no-deps", "--scale", "payments-worker=2", "payments-worker")
    assert restarted.returncode == 0, restarted.stderr
    # After the lease runs out another worker takes the job over and finishes it.
    wait_for(lambda: payment_status(customer, payment["id"]) == "succeeded", 90, "another worker to take over")
    assert stack.sql(f"SELECT count(*) FROM pay_audit_log WHERE chain_key = '{payment['id']}' AND event = 'payment_succeeded'") == "1"


def test_a_provider_outage_is_survived(stack: Stack) -> None:
    customer = register(stack, "pay4@example.com")
    order_id = new_order(customer)
    fake(stack, "fail", status=503, times=3)  # the adapter tries three times, then gives up
    failed = start_payment(customer, order_id)
    assert failed.status_code == 502 and failed.json()["code"] == "provider_unavailable"
    with customer.http() as http:
        listed = http.get("/payments").json()["items"]
    assert [p["status"] for p in listed][:1] == ["creating"]
    # The queued retry finishes the very same payment once the provider is back.
    wait_for(lambda: payment_status(customer, listed[0]["id"]) == "requires_payment", 90, "the retry")
    assert len([s for s in fake(stack, "state")["sessions"] if s["client_reference_id"] == listed[0]["id"]]) == 1


def test_reconcile_runs_from_the_command_line(stack: Stack) -> None:
    result = stack.compose("run", "--rm", "--no-deps", "payments-worker", "python", "-m", "app.payments.reconcile")
    assert result.returncode == 0, result.stderr
    assert "'payments'" in result.stdout and "'errors'" in result.stdout


def test_the_database_roles_script_gives_the_app_login_no_power_over_the_audit_log(stack: Stack) -> None:
    sql_file = (stack.root / "deploy" / "sql" / "roles.sql").read_text(encoding="utf-8")
    applied = stack.compose(
        "exec", "-T", "db", "psql", "-U", "app", "-d", "app", "-v", "ON_ERROR_STOP=1",
        "-v", "migrator_password=migr-pass-123", "-v", "app_password=app-pass-123", "-v", "database=app",
        stdin=sql_file,
    )
    assert applied.returncode == 0, applied.stderr
    login = ["exec", "-T", "-e", "PGPASSWORD=app-pass-123", "db", "psql", "-h", "127.0.0.1", "-U", "pay_shop_app", "-d", "app", "-At", "-c"]
    assert stack.compose(*login, "SELECT count(*) FROM pay_payments").returncode == 0
    for forbidden in (
        "UPDATE pay_audit_log SET event = 'x'",
        "DELETE FROM pay_audit_log",
        "TRUNCATE pay_audit_log",
        "CREATE TABLE should_not_exist (x int)",
        "DROP TABLE pay_payments",
    ):
        result = stack.compose(*login, forbidden)
        assert result.returncode != 0, forbidden
        assert "permission denied" in result.stderr or "must be owner" in result.stderr, result.stderr


def test_containers_run_unprivileged_and_the_worker_cannot_write_to_its_files(stack: Stack) -> None:
    uid = stack.compose("exec", "-T", "api", "id", "-u")
    assert uid.stdout.strip() == "10001"
    worker = stack.compose("exec", "-T", "payments-worker", "sh", "-c", "id -u; touch /srv/x 2>&1; echo $?")
    lines = worker.stdout.split()
    assert lines[0] == "10001" and lines[-1] != "0"


def test_unsafe_configuration_stops_a_container_before_it_does_anything(stack: Stack) -> None:
    live = "sk_live_" + "z" * 24
    result = stack.compose(
        "run", "--rm", "--no-deps", "-e", f"STRIPE_SECRET_KEY={live}", "payments-worker"
    )
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "live key is only accepted when APP_ENV=production" in output
    assert live not in output, "the key must never be printed"
    assert SECRET_KEY not in output
