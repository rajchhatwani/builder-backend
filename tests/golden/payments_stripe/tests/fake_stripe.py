"""A stand-in for the Stripe API (generated, tests only).

It runs as a real HTTP server on 127.0.0.1, so the real Stripe adapter (form encoding, headers,
retries, parsing, idempotency keys) is what the tests exercise. It follows the parts of Stripe's
behaviour the module depends on: bearer authentication, a pinned API version, idempotent POSTs (a
replayed key returns the first answer; the same key with other parameters is an error), Checkout
Sessions that move from open to complete or expired, refunds that cannot exceed what was paid,
disputes, and webhooks signed with Stripe's scheme. It is a stand-in, not Stripe: see
deploy/DEPLOYMENT.md for how to test against Stripe's test mode with your own keys.

Only the standard library is used, so a test outside the project can import this file too.
Run it on its own for manual experiments:  python -m tests.fake_stripe 12111 [host]
"""

import hashlib
import hmac
import json
import os
import threading
import time
import urllib.parse
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from pydantic import SecretStr

PROVIDER = "stripe"
WEBHOOK_PATH = "/payments/webhooks/stripe"
API_VERSION = "2024-06-20"
TEST_SECRET_KEY = "sk_test_" + "a" * 24
WEBHOOK_SECRET = "whsec_" + "b" * 32
OTHER_WEBHOOK_SECRET = "whsec_" + "c" * 32
SUPPORTS_SLOW = True  # payment methods that confirm later (bank debits)
SUPPORTS_LIVE_EVENT = True  # events carry a live/test flag
HAS_TIMESTAMP = True  # webhook signatures include a timestamp
SECRET_VALUES = (TEST_SECRET_KEY, WEBHOOK_SECRET, OTHER_WEBHOOK_SECRET)
# What the app is configured with in tests (environment variable -> value).
ENV = {"STRIPE_SECRET_KEY": TEST_SECRET_KEY, "STRIPE_WEBHOOK_SECRETS": WEBHOOK_SECRET}
ENV_API_BASE = "STRIPE_API_BASE"
ENV_WEBHOOK_SECRETS = "STRIPE_WEBHOOK_SECRETS"
ENV_KEY = "STRIPE_SECRET_KEY"
LIVE_ENV = {"STRIPE_SECRET_KEY": "sk_live_" + "a" * 24}


def settings_kwargs(**overrides: Any) -> dict[str, Any]:
    """Keyword arguments for PaymentsSettings that make a valid test-mode configuration."""
    base: dict[str, Any] = {
        "stripe_secret_key": SecretStr(TEST_SECRET_KEY),
        "stripe_webhook_secrets": SecretStr(WEBHOOK_SECRET),
        "app_env": "development",
        "stripe_api_base": "https://api.stripe.com",
    }
    base.update(overrides)
    return base


def live_settings_kwargs() -> dict[str, Any]:
    return settings_kwargs(app_env="production", stripe_secret_key=SecretStr("sk_live_" + "a" * 24))


def unsafe_settings() -> list[dict[str, Any]]:
    """Settings that must be refused (each is a change to the valid configuration)."""
    return [
        {"stripe_secret_key": None},
        {"stripe_secret_key": SecretStr("not-a-key")},
        {"stripe_secret_key": SecretStr("sk_test_short")},
        {"stripe_secret_key": SecretStr("sk_live_" + "a" * 24)},  # live key, not production
        {"app_env": "production"},  # test key in production
        {
            "app_env": "production",
            "stripe_secret_key": SecretStr("sk_live_" + "a" * 24),
            "stripe_api_base": "http://evil.example.com",
        },
        {"stripe_webhook_secrets": None},
        {"stripe_webhook_secrets": SecretStr("not-a-secret")},
        {"stripe_webhook_secrets": SecretStr("whsec_short")},
        {"stripe_api_base": "ftp://example.com"},
    ]


# --- webhooks -------------------------------------------------------------------------------


def sign(
    body: bytes,
    secret: str | None = None,
    timestamp: int | None = None,
    event_id: str | None = None,
) -> dict[str, str]:
    """The Stripe-Signature header for `body`, computed the way Stripe does it."""
    stamp = int(time.time()) if timestamp is None else timestamp
    key = (secret or WEBHOOK_SECRET).encode()
    digest = hmac.new(key, f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
    return {"Stripe-Signature": f"t={stamp},v1={digest}", "Content-Type": "application/json"}


def event_body(event_type: str, obj: dict[str, Any], *, livemode: bool = False) -> bytes:
    event = {
        "id": f"evt_test_{uuid.uuid4().hex[:20]}",
        "object": "event",
        "api_version": API_VERSION,
        "created": int(time.time()),
        "livemode": livemode,
        "type": event_type,
        "data": {"object": obj},
    }
    return json.dumps(event).encode("utf-8")


def signed_event(
    event_type: str, obj: dict[str, Any], *, livemode: bool = False, **sign_kwargs: Any
) -> tuple[bytes, dict[str, str]]:
    body = event_body(event_type, obj, livemode=livemode)
    return body, sign(body, **sign_kwargs)


def completed_event(session: dict[str, Any], secret: str | None = None) -> tuple[bytes, dict[str, str]]:
    return signed_event("checkout.session.completed", session, secret=secret)


# --- the fake account -------------------------------------------------------------------------


def _form(body: bytes) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(body.decode("ascii"), keep_blank_values=True))


def _expected_key() -> str:
    """The API key the stand-in accepts (a container can be given another with an env variable)."""
    return os.environ.get("FAKE_STRIPE_SECRET_KEY", TEST_SECRET_KEY)


@dataclass
class Call:
    method: str
    path: str
    authorized: bool
    version_ok: bool
    create_key: str | None  # what makes a repeated creation harmless (here: the idempotency key)
    amount: int | None = None
    success_url: str | None = None
    refund_amount: int | None = None


@dataclass
class Fake:
    """The state of the pretend Stripe account. Mutate it from tests to stage situations."""

    port: int = 0
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    refunds: dict[str, dict[str, Any]] = field(default_factory=dict)
    disputes: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: list[Call] = field(default_factory=list)
    _idempotent: dict[str, tuple[dict[str, str], tuple[int, dict[str, Any]]]] = field(
        default_factory=dict
    )
    # queued failures: each entry is (http status, body) returned instead of handling a request
    failures: list[tuple[int, dict[str, Any]]] = field(default_factory=list)
    amount_override: int | None = None  # a wrong amount to return, to test that it is caught
    refund_status: str = "succeeded"
    delay_seconds: float = 0.0  # slows every API answer, to test a crash in the middle of a call
    lock: threading.Lock = field(default_factory=threading.Lock)

    # --- staging helpers (the interface the shared tests use) -------------------------------

    def reset(self) -> None:
        with self.lock:
            self.sessions.clear()
            self.refunds.clear()
            self.disputes.clear()
            self.calls.clear()
            self._idempotent.clear()
            self.failures.clear()
            self.amount_override = None
            self.refund_status = "succeeded"
            self.delay_seconds = 0.0

    def only_session_id(self) -> str:
        assert len(self.sessions) == 1, f"expected one session, have {len(self.sessions)}"
        return next(iter(self.sessions))

    def session_amount(self, session_id: str) -> int:
        return int(self.sessions[session_id]["amount_total"])

    def intent_of(self, session_id: str) -> str:
        return str(self.sessions[session_id]["payment_intent"])

    def expected_create_key(self, payment_id: str) -> str:
        return f"pay_{payment_id}"

    def outage(self, times: int = 3) -> None:
        """The next `times` API calls fail with a server error (the adapter makes 3 attempts)."""
        self.failures[:] = [(503, {"error": {}})] * times

    def rejection(self, code: str, message: str) -> None:
        """The next API call is refused with `code` and a human sentence the app must not repeat."""
        self.failures[:] = [(400, {"error": {"code": code, "message": message}})]

    def pay(self, session_id: str, *, slow: bool = False) -> None:
        """The payer completes checkout. `slow` = a method that confirms later (bank debit)."""
        with self.lock:
            session = self.sessions[session_id]
            session["status"] = "complete"
            session["payment_status"] = "unpaid" if slow else "paid"
            session["payment_intent"] = session["payment_intent"] or f"pi_test_{uuid.uuid4().hex[:16]}"

    def confirm(self, session_id: str) -> None:
        with self.lock:
            self.sessions[session_id]["payment_status"] = "paid"

    def expire(self, session_id: str) -> None:
        with self.lock:
            self.sessions[session_id]["status"] = "expired"

    def dashboard_refund(self, payment_intent: str, amount: int, status: str = "succeeded") -> str:
        """A refund made in the provider's own dashboard, which this system did not ask for."""
        with self.lock:
            refund_id = f"re_test_{uuid.uuid4().hex[:16]}"
            self.refunds[refund_id] = self._refund_object(refund_id, payment_intent, amount, status, {})
            return refund_id

    def open_dispute(self, payment_intent: str, amount: int) -> str:
        with self.lock:
            dispute_id = f"dp_test_{uuid.uuid4().hex[:16]}"
            self.disputes[dispute_id] = {
                "id": dispute_id,
                "object": "dispute",
                "amount": amount,
                "currency": "usd",
                "status": "needs_response",
                "reason": "fraudulent",
                "payment_intent": payment_intent,
                "charge": "ch_test_1",
                "created": int(time.time()),
                "evidence_details": {"due_by": int(time.time()) + 7 * 86400},
            }
            return dispute_id

    def lose_dispute(self, dispute_id: str) -> None:
        self.disputes[dispute_id]["status"] = "lost"

    # --- signed webhooks the provider would send ---------------------------------------------

    def completed_event(self, session_id: str) -> tuple[bytes, dict[str, str]]:
        return signed_event("checkout.session.completed", self.sessions[session_id])

    def async_succeeded_event(self, session_id: str) -> tuple[bytes, dict[str, str]] | None:
        return signed_event("checkout.session.async_payment_succeeded", self.sessions[session_id])

    def async_failed_event(self, session_id: str) -> tuple[bytes, dict[str, str]] | None:
        return signed_event("checkout.session.async_payment_failed", self.sessions[session_id])

    def expired_event(self, session_id: str) -> tuple[bytes, dict[str, str]]:
        return signed_event("checkout.session.expired", self.sessions[session_id])

    def refund_event(self, refund_id: str) -> tuple[bytes, dict[str, str]]:
        return signed_event("refund.created", self.refunds[refund_id])

    def dispute_event(self, dispute_id: str, *, closed: bool = False) -> tuple[bytes, dict[str, str]]:
        name = "charge.dispute.closed" if closed else "charge.dispute.created"
        return signed_event(name, self.disputes[dispute_id])

    def ghost_event(self) -> tuple[bytes, dict[str, str]]:
        """A completed checkout for a payment this system has never heard of."""
        ghost = {
            "id": "cs_test_ghost", "object": "checkout.session", "status": "complete",
            "payment_status": "paid", "payment_intent": "pi_test_ghost", "amount_total": 100,
            "currency": "usd", "livemode": False, "url": None, "client_reference_id": None,
        }
        self.sessions["cs_test_ghost"] = dict(ghost)
        return signed_event("checkout.session.completed", ghost)

    def live_mode_event(self, session_id: str) -> tuple[bytes, dict[str, str]] | None:
        return signed_event("checkout.session.completed", self.sessions[session_id], livemode=True)

    def signed(self, body: bytes, secret: str | None = None) -> dict[str, str]:
        return sign(body, secret=secret)

    def multi_signature_headers(self, body: bytes) -> dict[str, str] | None:
        """A header holding a bad signature and a good one: the good one is enough."""
        stamp = int(time.time())
        good = sign(body, timestamp=stamp)["Stripe-Signature"].split("v1=")[1]
        return {"Stripe-Signature": f"t={stamp},v1={'0' * 64},v1={good}"}

    def forgeries(self, good_body: bytes) -> dict[str, tuple[bytes, dict[str, str]]]:
        """Webhooks an attacker could send. Every one must be refused, all the same way."""
        now = int(time.time())
        garbage = b"not json"
        no_id = json.dumps({"type": "x", "livemode": False, "data": {"object": {}}}).encode()
        return {
            "tampered body": (good_body.replace(b"paid", b"PAID"), sign(good_body)),
            "appended byte": (good_body + b" ", sign(good_body)),
            "wrong secret": (good_body, sign(good_body, secret=OTHER_WEBHOOK_SECRET)),
            "stale timestamp": (good_body, sign(good_body, timestamp=now - 3600)),
            "future timestamp": (good_body, sign(good_body, timestamp=now + 3600)),
            "no header": (good_body, {}),
            "empty header": (good_body, {"Stripe-Signature": ""}),
            "no v1": (good_body, {"Stripe-Signature": f"t={now}"}),
            "no timestamp": (good_body, {"Stripe-Signature": "v1=" + "0" * 64}),
            "non-hex v1": (good_body, {"Stripe-Signature": f"t={now},v1=" + "z" * 64}),
            "short v1": (good_body, {"Stripe-Signature": f"t={now},v1=abcd"}),
            "signature of other body": (good_body, sign(b"{}")),
            "only the old v0 scheme": (good_body, {"Stripe-Signature": f"t={now},v0=" + "0" * 64}),
            "too many parts": (
                good_body,
                {"Stripe-Signature": ",".join(f"v1={'0' * 64}" for _ in range(40))},
            ),
            "signed garbage": (garbage, sign(garbage)),
            "signed non-object": (b"[1,2]", sign(b"[1,2]")),
            "signed event without id": (no_id, sign(no_id)),
        }

    def created_checkouts(self) -> list[Call]:
        return [c for c in self.calls if c.method == "POST" and c.amount is not None]

    # --- request handling -----------------------------------------------------------------------

    @staticmethod
    def _refund_object(
        refund_id: str, payment_intent: str, amount: int, status: str, metadata: dict[str, str]
    ) -> dict[str, Any]:
        return {
            "id": refund_id,
            "object": "refund",
            "amount": amount,
            "currency": "usd",
            "status": status,
            "payment_intent": payment_intent,
            "metadata": metadata,
            "created": int(time.time()),
        }

    def handle(
        self, method: str, raw_path: str, headers: dict[str, str], body: bytes
    ) -> tuple[int, dict[str, Any]]:
        parsed = urllib.parse.urlsplit(raw_path)
        path = parsed.path
        query = dict(urllib.parse.parse_qsl(parsed.query))
        params = _form(body) if body else {}
        key = headers.get("idempotency-key")
        if self.delay_seconds and not path.startswith("/_fake"):
            time.sleep(self.delay_seconds)
        with self.lock:
            authorized = headers.get("authorization", "") == f"Bearer {_expected_key()}"
            self.calls.append(
                Call(
                    method,
                    path,
                    authorized,
                    headers.get("stripe-version") == API_VERSION,
                    key,
                    amount=_int_or_none(params.get("line_items[0][price_data][unit_amount]")),
                    success_url=params.get("success_url"),
                    refund_amount=_int_or_none(params.get("amount")) if "/refunds" in path else None,
                )
            )
            if path.startswith("/_fake"):
                return self._route(method, path, params, query)
            if self.failures:
                return self.failures.pop(0)
            if not authorized:
                return 401, {"error": {"type": "invalid_request_error", "code": "api_key_invalid"}}
            if key is not None and method == "POST":
                seen = self._idempotent.get(key)
                if seen is not None:
                    if seen[0] != params:
                        return 400, {"error": {"type": "idempotency_error"}}
                    return seen[1]
            result = self._route(method, path, params, query)
            if key is not None and method == "POST" and result[0] < 300:
                self._idempotent[key] = (params, result)
            return result

    def _control(
        self, parts: list[str], query: dict[str, str]
    ) -> tuple[int, dict[str, Any]]:
        """Test-only remote control (so a test outside this process can stage the account)."""
        action = parts[1] if len(parts) > 1 else ""
        target = parts[2] if len(parts) > 2 else ""
        if action == "state":
            return 200, {
                "sessions": list(self.sessions.values()),
                "refunds": list(self.refunds.values()),
                "calls": len(self.calls),
            }
        if action == "pay" and target in self.sessions:
            session = self.sessions[target]
            session["status"] = "complete"
            session["payment_status"] = "unpaid" if query.get("slow") else "paid"
            session["payment_intent"] = session["payment_intent"] or f"pi_test_{uuid.uuid4().hex[:16]}"
            return 200, session
        if action == "expire" and target in self.sessions:
            self.sessions[target]["status"] = "expired"
            return 200, self.sessions[target]
        if action == "fail":
            status = int(query.get("status", "503"))
            self.failures.extend([(status, {"error": {}})] * int(query.get("times", "1")))
            return 200, {"queued": len(self.failures)}
        if action == "delay":
            self.delay_seconds = float(query.get("seconds", "0"))
            return 200, {"delay": self.delay_seconds}
        if action == "reset":
            self.sessions.clear()
            self.refunds.clear()
            self.failures.clear()
            self.delay_seconds = 0.0
            return 200, {}
        return 404, {"error": {"code": "unknown_control"}}

    def _route(
        self, method: str, path: str, params: dict[str, str], query: dict[str, str]
    ) -> tuple[int, dict[str, Any]]:
        parts = path.strip("/").split("/")
        if parts[0] == "_fake":
            return self._control(parts, query)
        if parts[:3] == ["v1", "checkout", "sessions"]:
            return self._sessions(method, parts[3:], params)
        if parts[:2] == ["v1", "refunds"]:
            return self._refunds_route(method, parts[2:], params, query)
        if parts[:2] == ["v1", "disputes"] and method == "GET" and len(parts) == 3:
            found = self.disputes.get(parts[2])
            return (200, found) if found else (404, {"error": {"code": "resource_missing"}})
        return 404, {"error": {"type": "invalid_request_error", "code": "unknown_route"}}

    def _sessions(
        self, method: str, rest: list[str], params: dict[str, str]
    ) -> tuple[int, dict[str, Any]]:
        if method == "POST" and not rest:
            amount = int(params["line_items[0][price_data][unit_amount]"])
            session_id = f"cs_test_{uuid.uuid4().hex[:20]}"
            session = {
                "id": session_id,
                "object": "checkout.session",
                "url": f"https://checkout.stripe.test/c/pay/{session_id}",
                "status": "open",
                "payment_status": "unpaid",
                "payment_intent": None,
                "amount_total": self.amount_override if self.amount_override else amount,
                "currency": params["line_items[0][price_data][currency]"],
                "client_reference_id": params.get("client_reference_id"),
                "metadata": {"payment_id": params.get("metadata[payment_id]", "")},
                "livemode": False,
                "expires_at": int(params["expires_at"]),
            }
            assert params["mode"] == "payment"
            self.sessions[session_id] = session
            return 200, session
        session = self.sessions.get(rest[0]) if rest else None
        if session is None:
            return 404, {"error": {"type": "invalid_request_error", "code": "resource_missing"}}
        if method == "GET" and len(rest) == 1:
            return 200, session
        if method == "POST" and rest[1:] == ["expire"]:
            if session["status"] != "open":
                return 400, {"error": {"type": "invalid_request_error", "code": "invalid_state"}}
            session["status"] = "expired"
            return 200, session
        return 404, {"error": {"code": "unknown_route"}}

    def _refunds_route(
        self, method: str, rest: list[str], params: dict[str, str], query: dict[str, str]
    ) -> tuple[int, dict[str, Any]]:
        if method == "POST" and not rest:
            intent = params["payment_intent"]
            amount = int(params["amount"])
            paid = next(s for s in self.sessions.values() if s["payment_intent"] == intent)["amount_total"]
            taken = sum(
                r["amount"]
                for r in self.refunds.values()
                if r["payment_intent"] == intent and r["status"] != "failed"
            )
            if amount > paid - taken:
                return 400, {"error": {"type": "invalid_request_error", "code": "charge_already_refunded"}}
            refund_id = f"re_test_{uuid.uuid4().hex[:16]}"
            metadata = {"refund_id": params.get("metadata[refund_id]", "")}
            refund = self._refund_object(refund_id, intent, amount, self.refund_status, metadata)
            self.refunds[refund_id] = refund
            return 200, refund
        if method == "GET" and not rest:
            intent = query.get("payment_intent")
            data = [r for r in self.refunds.values() if r["payment_intent"] == intent]
            return 200, {"object": "list", "data": data}
        if method == "GET" and len(rest) == 1:
            found = self.refunds.get(rest[0])
            return (200, found) if found else (404, {"error": {"code": "resource_missing"}})
        return 404, {"error": {"code": "unknown_route"}}


def _int_or_none(value: str | None) -> int | None:
    return int(value) if value is not None and value.lstrip("-").isdigit() else None


class _Handler(BaseHTTPRequestHandler):
    fake: Fake

    def _serve(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        headers = {k.lower(): v for k, v in self.headers.items()}
        status, payload = self.fake.handle(self.command, self.path, headers, body)
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = _serve  # noqa: N815

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - quiet
        return


def start_fake(host: str = "127.0.0.1", port: int = 0) -> tuple[Fake, ThreadingHTTPServer]:
    fake = Fake()
    handler = type("Handler", (_Handler,), {"fake": fake})
    server = ThreadingHTTPServer((host, port), handler)
    fake.port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return fake, server


if __name__ == "__main__":  # pragma: no cover - manual experiments and the Docker stack test
    import sys

    stand_in, httpd = start_fake(
        sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 0
    )
    print(f"fake Stripe on port {stand_in.port}")  # noqa: T201
    threading.Event().wait()
    httpd.shutdown()
