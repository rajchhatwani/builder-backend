"""A stand-in for the Razorpay API (generated, tests only).

It runs as a real HTTP server on 127.0.0.1, so the real Razorpay adapter (JSON bodies, Basic
authentication, retries, parsing, the refund idempotency header) is what the tests exercise. It
follows the parts of Razorpay's behaviour the module depends on: Payment Links with unique
reference ids (a repeat is refused, and the existing link can be found by that reference),
links that move from created to paid, expired or cancelled, refunds that cannot exceed what was
paid and that honour X-Refund-Idempotency, disputes, and webhooks signed with HMAC-SHA256 over the
raw body plus a unique event id header. It is a stand-in, not Razorpay: see deploy/DEPLOYMENT.md
for how to test against Razorpay's test mode with your own keys.

Only the standard library (and pydantic) is used, so a test outside the project can import this
file too.  Run it on its own:  python -m tests.fake_razorpay 12111 [host]
"""

import base64
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

PROVIDER = "razorpay"
WEBHOOK_PATH = "/payments/webhooks/razorpay"
TEST_KEY_ID = "rzp_test_" + "A1b2C3d4E5f6G7"
TEST_KEY_SECRET = "s" * 24
WEBHOOK_SECRET = "w" * 32
OTHER_WEBHOOK_SECRET = "x" * 32
SUPPORTS_SLOW = False  # a payment link ends when it is paid; there is no "confirms later" state
SUPPORTS_LIVE_EVENT = False  # Razorpay entities do not say whether they are test or live
HAS_TIMESTAMP = False  # webhook signatures carry no timestamp
SECRET_VALUES = (TEST_KEY_SECRET, WEBHOOK_SECRET, OTHER_WEBHOOK_SECRET)
ENV = {
    "RAZORPAY_KEY_ID": TEST_KEY_ID,
    "RAZORPAY_KEY_SECRET": TEST_KEY_SECRET,
    "RAZORPAY_WEBHOOK_SECRETS": WEBHOOK_SECRET,
}
ENV_API_BASE = "RAZORPAY_API_BASE"
ENV_WEBHOOK_SECRETS = "RAZORPAY_WEBHOOK_SECRETS"
ENV_KEY = "RAZORPAY_KEY_SECRET"
LIVE_ENV = {"RAZORPAY_KEY_ID": "rzp_live_" + "A1b2C3d4E5f6G7"}


def settings_kwargs(**overrides: Any) -> dict[str, Any]:
    """Keyword arguments for PaymentsSettings that make a valid test-mode configuration."""
    base: dict[str, Any] = {
        "razorpay_key_id": TEST_KEY_ID,
        "razorpay_key_secret": SecretStr(TEST_KEY_SECRET),
        "razorpay_webhook_secrets": SecretStr(WEBHOOK_SECRET),
        "app_env": "development",
        "razorpay_api_base": "https://api.razorpay.com",
    }
    base.update(overrides)
    return base


def live_settings_kwargs() -> dict[str, Any]:
    return settings_kwargs(app_env="production", razorpay_key_id="rzp_live_" + "A1b2C3d4E5f6G7")


def unsafe_settings() -> list[dict[str, Any]]:
    """Settings that must be refused (each is a change to the valid configuration)."""
    return [
        {"razorpay_key_id": None},
        {"razorpay_key_id": "not-a-key"},
        {"razorpay_key_id": "rzp_test_x"},
        {"razorpay_key_secret": None},
        {"razorpay_key_secret": SecretStr("short")},
        {"razorpay_key_id": "rzp_live_" + "A1b2C3d4E5f6G7"},  # live key, not production
        {"app_env": "production"},  # test key in production
        {
            "app_env": "production",
            "razorpay_key_id": "rzp_live_" + "A1b2C3d4E5f6G7",
            "razorpay_api_base": "http://evil.example.com",
        },
        {"razorpay_webhook_secrets": None},
        {"razorpay_webhook_secrets": SecretStr("short")},
        {"razorpay_api_base": "ftp://example.com"},
    ]


# --- webhooks -------------------------------------------------------------------------------


def sign(
    body: bytes,
    secret: str | None = None,
    timestamp: int | None = None,
    event_id: str | None = None,
) -> dict[str, str]:
    """The headers Razorpay sends: HMAC-SHA256 of the raw body, and a unique event id."""
    digest = hmac.new((secret or WEBHOOK_SECRET).encode(), body, hashlib.sha256).hexdigest()
    return {
        "X-Razorpay-Signature": digest,
        "X-Razorpay-Event-Id": event_id or f"evt{uuid.uuid4().hex[:18]}",
        "Content-Type": "application/json",
    }


def event_body(event: str, payload: dict[str, Any]) -> bytes:
    return json.dumps(
        {
            "entity": "event",
            "account_id": "acc_test",
            "event": event,
            "contains": list(payload),
            "payload": payload,
            "created_at": int(time.time()),
        }
    ).encode("utf-8")


def signed_event(event: str, payload: dict[str, Any], **sign_kwargs: Any) -> tuple[bytes, dict[str, str]]:
    body = event_body(event, payload)
    return body, sign(body, **sign_kwargs)


def _link_payload(link: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"payment_link": {"entity": link}}
    payments = link.get("payments")
    if payments:
        payload["payment"] = {"entity": {"id": payments[0]["payment_id"], "status": "captured"}}
        payload["order"] = {"entity": {"id": "XyZ123", "status": "paid"}}
    return payload


def completed_event(link: dict[str, Any], secret: str | None = None) -> tuple[bytes, dict[str, str]]:
    return signed_event("payment_link.paid", _link_payload(link), secret=secret)


# --- the fake account -------------------------------------------------------------------------


def _expected_credentials() -> tuple[str, str]:
    return (
        os.environ.get("FAKE_RAZORPAY_KEY_ID", TEST_KEY_ID),
        os.environ.get("FAKE_RAZORPAY_KEY_SECRET", TEST_KEY_SECRET),
    )


@dataclass
class Call:
    method: str
    path: str
    authorized: bool
    version_ok: bool
    create_key: str | None  # what makes a repeated creation harmless (here: the reference id)
    amount: int | None = None
    success_url: str | None = None
    refund_amount: int | None = None


@dataclass
class Fake:
    """The state of the pretend Razorpay account. Mutate it from tests to stage situations."""

    port: int = 0
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)  # payment links by id
    refunds: dict[str, dict[str, Any]] = field(default_factory=dict)
    disputes: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: list[Call] = field(default_factory=list)
    _idempotent: dict[str, tuple[dict[str, Any], tuple[int, dict[str, Any]]]] = field(
        default_factory=dict
    )
    failures: list[tuple[int, dict[str, Any]]] = field(default_factory=list)
    amount_override: int | None = None
    refund_status: str = "processed"
    delay_seconds: float = 0.0
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
            self.refund_status = "processed"
            self.delay_seconds = 0.0

    def only_session_id(self) -> str:
        assert len(self.sessions) == 1, f"expected one payment link, have {len(self.sessions)}"
        return next(iter(self.sessions))

    def session_amount(self, session_id: str) -> int:
        return int(self.sessions[session_id]["amount"])

    def intent_of(self, session_id: str) -> str:
        return str(self.sessions[session_id]["payments"][0]["payment_id"])

    def expected_create_key(self, payment_id: str) -> str:
        return payment_id

    def outage(self, times: int = 3) -> None:
        self.failures[:] = [(503, {"error": {}})] * times

    def rejection(self, code: str, message: str) -> None:
        self.failures[:] = [
            (400, {"error": {"code": "BAD_REQUEST_ERROR", "reason": code, "description": message}})
        ]

    def pay(self, session_id: str, *, slow: bool = False) -> None:
        if slow:
            raise NotImplementedError("Razorpay payment links have no slow-confirmation state")
        with self.lock:
            link = self.sessions[session_id]
            link["status"] = "paid"
            link["amount_paid"] = link["amount"]
            link["payments"] = [
                {
                    "payment_id": f"pay_{uuid.uuid4().hex[:14]}",
                    "plink_id": session_id,
                    "amount": link["amount"],
                    "method": "upi",
                    "status": "captured",
                    "created_at": int(time.time()),
                }
            ]

    def confirm(self, session_id: str) -> None:
        raise NotImplementedError

    def expire(self, session_id: str) -> None:
        with self.lock:
            self.sessions[session_id]["status"] = "expired"

    def dashboard_refund(self, payment_intent: str, amount: int, status: str = "succeeded") -> str:
        with self.lock:
            refund_id = f"rfnd_{uuid.uuid4().hex[:14]}"
            mapped = {"succeeded": "processed"}.get(status, status)
            self.refunds[refund_id] = self._refund_object(refund_id, payment_intent, amount, mapped, {})
            return refund_id

    def open_dispute(self, payment_intent: str, amount: int) -> str:
        with self.lock:
            dispute_id = f"disp_{uuid.uuid4().hex[:14]}"
            self.disputes[dispute_id] = {
                "id": dispute_id,
                "entity": "dispute",
                "payment_id": payment_intent,
                "amount": amount,
                "currency": "INR",
                "reason_code": "fraud",
                "phase": "chargeback",
                "status": "open",
                "respond_by": int(time.time()) + 7 * 86400,
                "created_at": int(time.time()),
            }
            return dispute_id

    def lose_dispute(self, dispute_id: str) -> None:
        self.disputes[dispute_id]["status"] = "lost"

    # --- signed webhooks the provider would send ---------------------------------------------

    def completed_event(self, session_id: str) -> tuple[bytes, dict[str, str]]:
        return signed_event("payment_link.paid", _link_payload(self.sessions[session_id]))

    def async_succeeded_event(self, session_id: str) -> tuple[bytes, dict[str, str]] | None:
        return None

    def async_failed_event(self, session_id: str) -> tuple[bytes, dict[str, str]] | None:
        return None

    def expired_event(self, session_id: str) -> tuple[bytes, dict[str, str]]:
        return signed_event("payment_link.expired", _link_payload(self.sessions[session_id]))

    def refund_event(self, refund_id: str) -> tuple[bytes, dict[str, str]]:
        refund = self.refunds[refund_id]
        payload = {
            "refund": {"entity": refund},
            "payment": {"entity": {"id": refund["payment_id"]}},
        }
        return signed_event("refund.processed", payload)

    def dispute_event(self, dispute_id: str, *, closed: bool = False) -> tuple[bytes, dict[str, str]]:
        name = "payment.dispute.closed" if closed else "payment.dispute.created"
        return signed_event(name, {"dispute": {"entity": self.disputes[dispute_id]}})

    def ghost_event(self) -> tuple[bytes, dict[str, str]]:
        ghost = {
            "id": "plink_ghost", "reference_id": str(uuid.uuid4()), "status": "paid", "amount": 100,
            "amount_paid": 100, "currency": "INR", "short_url": "https://rzp.io/i/ghost",
            "payments": [{"payment_id": "pay_ghost", "amount": 100, "status": "captured"}],
        }
        self.sessions["plink_ghost"] = dict(ghost)
        return signed_event("payment_link.paid", _link_payload(ghost))

    def live_mode_event(self, session_id: str) -> tuple[bytes, dict[str, str]] | None:
        return None

    def signed(self, body: bytes, secret: str | None = None) -> dict[str, str]:
        return sign(body, secret=secret)

    def multi_signature_headers(self, body: bytes) -> dict[str, str] | None:
        return None

    def forgeries(self, good_body: bytes) -> dict[str, tuple[bytes, dict[str, str]]]:
        """Webhooks an attacker could send. Every one must be refused, all the same way."""
        garbage = b"not json"
        no_event = json.dumps({"payload": {}}).encode()
        good = sign(good_body)
        return {
            "tampered body": (good_body.replace(b"paid", b"PAID"), good),
            "appended byte": (good_body + b" ", good),
            "wrong secret": (good_body, sign(good_body, secret=OTHER_WEBHOOK_SECRET)),
            "no header": (good_body, {"X-Razorpay-Event-Id": "evt1"}),
            "empty signature": (good_body, {"X-Razorpay-Signature": "", "X-Razorpay-Event-Id": "evt1"}),
            "non-hex signature": (good_body, {"X-Razorpay-Signature": "z" * 64, "X-Razorpay-Event-Id": "evt1"}),
            "short signature": (good_body, {"X-Razorpay-Signature": "abcd", "X-Razorpay-Event-Id": "evt1"}),
            "signature of other body": (good_body, sign(b"{}")),
            "valid signature, no event id": (
                good_body,
                {"X-Razorpay-Signature": good["X-Razorpay-Signature"]},
            ),
            "valid signature, bad event id": (
                good_body,
                {"X-Razorpay-Signature": good["X-Razorpay-Signature"], "X-Razorpay-Event-Id": "a b"},
            ),
            "signed garbage": (garbage, sign(garbage)),
            "signed non-object": (b"[1,2]", sign(b"[1,2]")),
            "signed event without a name": (no_event, sign(no_event)),
        }

    def created_checkouts(self) -> list[Call]:
        return [c for c in self.calls if c.method == "POST" and c.amount is not None]

    # --- request handling -----------------------------------------------------------------------

    @staticmethod
    def _refund_object(
        refund_id: str, payment_id: str, amount: int, status: str, notes: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "id": refund_id,
            "entity": "refund",
            "payment_id": payment_id,
            "amount": amount,
            "currency": "INR",
            "status": status,
            "notes": notes,
            "receipt": notes.get("refund_id"),
            "created_at": int(time.time()),
        }

    def handle(
        self, method: str, raw_path: str, headers: dict[str, str], body: bytes
    ) -> tuple[int, dict[str, Any]]:
        parsed = urllib.parse.urlsplit(raw_path)
        path = parsed.path
        query = dict(urllib.parse.parse_qsl(parsed.query))
        params: dict[str, Any] = json.loads(body) if body else {}
        if self.delay_seconds and not path.startswith("/_fake"):
            time.sleep(self.delay_seconds)
        key = headers.get("x-refund-idempotency")
        key_id, key_secret = _expected_credentials()
        expected = "Basic " + base64.b64encode(f"{key_id}:{key_secret}".encode()).decode()
        with self.lock:
            authorized = headers.get("authorization", "") == expected
            self.calls.append(
                Call(
                    method,
                    path,
                    authorized,
                    True,
                    params.get("reference_id") if path == "/v1/payment_links" else key,
                    amount=params.get("amount") if path == "/v1/payment_links" and method == "POST" else None,
                    success_url=params.get("callback_url"),
                    refund_amount=params.get("amount") if path.endswith("/refund") else None,
                )
            )
            if path.startswith("/_fake"):
                return self._route(method, path, params, query)
            if self.failures:
                return self.failures.pop(0)
            if not authorized:
                return 401, {"error": {"code": "BAD_REQUEST_ERROR", "reason": "authentication_failed"}}
            if key is not None and method == "POST":
                if len(key) < 10:
                    return 400, {"error": {"code": "BAD_REQUEST_ERROR", "reason": "invalid_idempotency_key"}}
                seen = self._idempotent.get(key)
                if seen is not None:
                    if seen[0] != params:
                        return 409, {"error": {"code": "BAD_REQUEST_ERROR", "reason": "idempotency_conflict"}}
                    return seen[1]
            result = self._route(method, path, params, query)
            if key is not None and method == "POST" and result[0] < 300:
                self._idempotent[key] = (params, result)
            return result

    def _control(self, parts: list[str], query: dict[str, str]) -> tuple[int, dict[str, Any]]:
        """Test-only remote control (so a test outside this process can stage the account)."""
        action = parts[1] if len(parts) > 1 else ""
        target = parts[2] if len(parts) > 2 else ""
        if action == "state":
            return 200, {
                "sessions": [dict(s, client_reference_id=s.get("reference_id")) for s in self.sessions.values()],
                "refunds": list(self.refunds.values()),
                "calls": len(self.calls),
            }
        if action == "pay" and target in self.sessions:
            link = self.sessions[target]
            link["status"] = "paid"
            link["amount_paid"] = link["amount"]
            link["payments"] = [
                {"payment_id": f"pay_{uuid.uuid4().hex[:14]}", "plink_id": target, "amount": link["amount"],
                 "method": "upi", "status": "captured", "created_at": int(time.time())}
            ]
            return 200, link
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
        self, method: str, path: str, params: dict[str, Any], query: dict[str, str]
    ) -> tuple[int, dict[str, Any]]:
        parts = path.strip("/").split("/")
        if parts[0] == "_fake":
            return self._control(parts, query)
        if parts[:2] == ["v1", "payment_links"]:
            return self._links(method, parts[2:], params, query)
        if parts[:2] == ["v1", "payments"] and len(parts) >= 4:
            return self._payment_routes(method, parts[2:], params, query)
        if parts[:2] == ["v1", "refunds"] and method == "GET" and len(parts) == 3:
            found = self.refunds.get(parts[2])
            return (200, found) if found else self._missing()
        if parts[:2] == ["v1", "disputes"] and method == "GET" and len(parts) == 3:
            found = self.disputes.get(parts[2])
            return (200, found) if found else self._missing()
        return 404, {"error": {"code": "BAD_REQUEST_ERROR", "reason": "unknown_route"}}

    @staticmethod
    def _missing() -> tuple[int, dict[str, Any]]:
        return 400, {"error": {"code": "BAD_REQUEST_ERROR", "reason": "id_not_found"}}

    def _links(
        self, method: str, rest: list[str], params: dict[str, Any], query: dict[str, str]
    ) -> tuple[int, dict[str, Any]]:
        if method == "POST" and not rest:
            reference = params.get("reference_id")
            if any(k["reference_id"] == reference for k in self.sessions.values()):
                return 400, {"error": {"code": "BAD_REQUEST_ERROR", "reason": "reference_id_already_used"}}
            amount = int(params["amount"])
            if amount < 100:
                return 400, {"error": {"code": "BAD_REQUEST_ERROR", "reason": "amount_too_small"}}
            link_id = f"plink_{uuid.uuid4().hex[:14]}"
            link = {
                "id": link_id,
                "short_url": f"https://rzp.io/i/{uuid.uuid4().hex[:8]}",
                "status": "created",
                "amount": self.amount_override if self.amount_override else amount,
                "amount_paid": 0,
                "currency": params.get("currency", "INR"),
                "accept_partial": False,
                "reference_id": reference,
                "description": params.get("description"),
                "notes": params.get("notes", {}),
                "callback_url": params.get("callback_url"),
                "expire_by": params.get("expire_by"),
                "payments": None,
            }
            assert params.get("callback_method") == "get"
            self.sessions[link_id] = link
            return 200, link
        if method == "GET" and not rest:
            reference = query.get("reference_id")
            links = [k for k in self.sessions.values() if reference in (None, k["reference_id"])]
            return 200, {"payment_links": links}
        link = self.sessions.get(rest[0]) if rest else None
        if link is None:
            return self._missing()
        if method == "GET" and len(rest) == 1:
            return 200, link
        if method == "POST" and rest[1:] == ["cancel"]:
            if link["status"] != "created":
                return 400, {"error": {"code": "BAD_REQUEST_ERROR", "reason": "invalid_state"}}
            link["status"] = "cancelled"
            return 200, link
        return 404, {"error": {"code": "BAD_REQUEST_ERROR", "reason": "unknown_route"}}

    def _payment_routes(
        self, method: str, rest: list[str], params: dict[str, Any], query: dict[str, str]
    ) -> tuple[int, dict[str, Any]]:
        payment_id = rest[0]
        link = next(
            (k for k in self.sessions.values() if k.get("payments") and k["payments"][0]["payment_id"] == payment_id),
            None,
        )
        if link is None:
            return self._missing()
        if method == "POST" and rest[1:] == ["refund"]:
            amount = int(params["amount"])
            taken = sum(
                r["amount"] for r in self.refunds.values()
                if r["payment_id"] == payment_id and r["status"] != "failed"
            )
            if amount > link["amount"] - taken:
                return 400, {"error": {"code": "BAD_REQUEST_ERROR", "reason": "refund_amount_exceeds_payment"}}
            refund_id = f"rfnd_{uuid.uuid4().hex[:14]}"
            refund = self._refund_object(refund_id, payment_id, amount, self.refund_status, params.get("notes", {}))
            self.refunds[refund_id] = refund
            return 200, refund
        if method == "GET" and rest[1:] == ["refunds"]:
            items = [r for r in self.refunds.values() if r["payment_id"] == payment_id]
            return 200, {"entity": "collection", "count": len(items), "items": items}
        return 404, {"error": {"code": "BAD_REQUEST_ERROR", "reason": "unknown_route"}}


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
    print(f"fake Razorpay on port {stand_in.port}")  # noqa: T201
    threading.Event().wait()
    httpd.shutdown()
