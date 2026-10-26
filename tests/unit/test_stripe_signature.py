"""Stripe webhook signature verification (Phase C.3), as a pure function.

Scheme: header `t=<unix>,v1=<hex hmac-sha256(secret, "<t>.<raw body>")>[,v1=...]`.
Nothing is parsed before the signature passes; timestamps outside the tolerance are
refused so a captured delivery cannot be replayed later.
"""

import hashlib
import hmac
import json

import pytest

from app.services.stripe_client import WebhookSignatureError, verify_webhook

NOW = 1_800_000_000
BODY = json.dumps(
    {"id": "evt_1", "type": "invoice.payment_failed", "data": {"object": {}}}
).encode()


def _sig(secret: str, t: int = NOW, body: bytes = BODY) -> str:
    return hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()


def test_valid_signature_returns_the_parsed_event() -> None:
    event = verify_webhook(BODY, f"t={NOW},v1={_sig('whsec_a')}", ["whsec_a"], now=NOW)
    assert event["id"] == "evt_1"


def test_any_of_several_signatures_or_secrets_may_match() -> None:
    header = f"t={NOW},v1={'0' * 64},v1={_sig('whsec_new')}"
    assert verify_webhook(BODY, header, ["whsec_old", "whsec_new"], now=NOW)["id"] == "evt_1"


@pytest.mark.parametrize(
    "header",
    [
        "",
        "garbage",
        f"t={NOW}",
        f"v1={_sig('whsec_a')}",
        f"t=abc,v1={_sig('whsec_a')}",
        f"t={NOW},v1=nothex",
        f"t={NOW},v0={_sig('whsec_a')}",  # only v1 is a real signature scheme
        ",".join([f"v1={'0' * 64}"] * 50) + f",t={NOW}",  # oversized header
    ],
)
def test_malformed_headers_are_rejected(header: str) -> None:
    with pytest.raises(WebhookSignatureError):
        verify_webhook(BODY, header, ["whsec_a"], now=NOW)


def test_wrong_secret_or_altered_body_is_rejected() -> None:
    with pytest.raises(WebhookSignatureError):
        verify_webhook(BODY, f"t={NOW},v1={_sig('whsec_b')}", ["whsec_a"], now=NOW)
    with pytest.raises(WebhookSignatureError):
        verify_webhook(BODY + b" ", f"t={NOW},v1={_sig('whsec_a')}", ["whsec_a"], now=NOW)


@pytest.mark.parametrize("skew", [-301, 301])
def test_timestamp_outside_tolerance_is_rejected(skew: int) -> None:
    t = NOW + skew
    with pytest.raises(WebhookSignatureError):
        verify_webhook(BODY, f"t={t},v1={_sig('whsec_a', t)}", ["whsec_a"], now=NOW, tolerance=300)


def test_no_configured_secret_rejects_everything() -> None:
    with pytest.raises(WebhookSignatureError):
        verify_webhook(BODY, f"t={NOW},v1={_sig('')}", [], now=NOW)


def test_signed_but_non_json_body_is_rejected() -> None:
    body = b"not json"
    with pytest.raises(WebhookSignatureError):
        verify_webhook(body, f"t={NOW},v1={_sig('whsec_a', body=body)}", ["whsec_a"], now=NOW)
