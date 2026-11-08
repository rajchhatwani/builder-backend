"""Adversarial review: Stripe webhook robustness (REQ-§6.3, §10, §12.C).
Run: uv run python -m pytest review/tests/test_adv_stripe.py -p no:cacheprovider -q
"""
import json
import time
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.platform import AuditLog, Subscription
from tests.api.conftest import ClientFor
from tests.api.test_billing_webhooks import (  # noqa: F401
    SECRET, WEBHOOK, checkout_completed, deliver, event, sign, subscription_obj, webhook_configured,
)

pytestmark = pytest.mark.usefixtures("webhook_configured")


async def raw(client, payload: bytes, sig: str | None = None):  # noqa: ANN001
    h = {"Content-Type": "application/json"}
    if sig is not None:
        h["Stripe-Signature"] = sig
    return await client.post(WEBHOOK, content=payload, headers=h)


async def test_signature_variants(anon_client: AsyncClient) -> None:
    body = json.dumps(event("ping", {})).encode()
    now = int(time.time())
    cases = {
        "missing": None,
        "garbage": "x",
        "wrong_secret": sign(body, "whsec_wrong"),
        "old_timestamp": sign(body, timestamp=now - 100000),
        "future_timestamp": sign(body, timestamp=now + 100000),
        "tampered": sign(body + b" "),
        "v0_only": "t=%d,v0=%s" % (now, "0" * 64),
        "empty_v1": "t=%d,v1=" % now,
        "non_numeric_t": "t=abc,v1=" + "0" * 64,
    }
    for name, sig in cases.items():
        r = await raw(anon_client, body, sig)
        assert r.status_code == 400, (name, r.status_code, r.text)
        assert "secret" not in r.text.lower() and "signature" not in r.text.lower(), (name, r.text)


async def test_signed_but_malformed_events_never_500(anon_client: AsyncClient) -> None:
    bad = []
    payloads = [
        b"{not json", b"[]", b"null", b'"str"', b"{}",
        json.dumps({"type": "customer.subscription.updated"}).encode(),            # no id / data
        json.dumps({"id": "e1", "type": "customer.subscription.updated", "data": None}).encode(),
        json.dumps({"id": "e2", "type": "customer.subscription.updated", "data": {"object": "x"}}).encode(),
        json.dumps({"id": "e3", "type": "checkout.session.completed", "data": {"object": {"mode": "subscription", "client_reference_id": "nope"}}}).encode(),
        json.dumps({"id": "e4", "type": "invoice.payment_failed", "data": {"object": {"subscription": {"id": 5}}}}).encode(),
        json.dumps({"id": "e5", "type": "customer.subscription.updated", "created": "abc", "data": {"object": {"id": "sub_x", "metadata": {"organization_id": str(uuid.uuid4())}}}}).encode(),
    ]
    for p in payloads:
        try:
            r = await raw(anon_client, p, sign(p))
        except Exception as e:  # noqa: BLE001
            bad.append((p[:60], f"raised {type(e).__name__}"))
            continue
        if r.status_code >= 500:
            bad.append((p[:60], r.status_code))
    assert bad == [], bad


async def test_webhook_oversize_and_get(anon_client: AsyncClient) -> None:
    p = b"x" * (300 * 1024)
    r = await raw(anon_client, p, sign(p))
    assert r.status_code == 400
    assert (await anon_client.get(WEBHOOK)).status_code in (404, 405)


async def test_out_of_order_recovery_clears_past_due_only_via_newer_event(client_for: ClientFor, anon_client: AsyncClient, session_factory) -> None:  # noqa: ANN001
    owner = await client_for("stripe@example.com")
    org = (await owner.post("/orgs", json={"name": "S", "slug": "stripe-co"})).json()
    oid = uuid.UUID(org["id"])
    t0 = int(time.time())
    assert (await deliver(anon_client, event("checkout.session.completed", checkout_completed(oid), created=t0))).status_code == 200
    assert (await deliver(anon_client, event("invoice.payment_failed", {"id": "in_1", "subscription": "sub_123", "customer": "cus_123"}, created=t0 + 10))).status_code == 200
    async with session_factory() as s:
        sub = await s.get(Subscription, oid)
        assert sub.status.value == "past_due"
    # an OLDER 'active' update (created before the failure) must not clear past_due
    await deliver(anon_client, event("customer.subscription.updated", subscription_obj(oid, status="active"), created=t0 + 5))
    async with session_factory() as s:
        assert (await s.get(Subscription, oid)).status.value == "past_due"
    # a newer one does
    await deliver(anon_client, event("customer.subscription.updated", subscription_obj(oid, status="active"), created=t0 + 20))
    async with session_factory() as s:
        assert (await s.get(Subscription, oid)).status.value == "active"


async def test_audit_rows_for_stripe_contain_no_customer_or_card_data(client_for: ClientFor, anon_client: AsyncClient, session_factory) -> None:  # noqa: ANN001
    owner = await client_for("stripe2@example.com")
    org = (await owner.post("/orgs", json={"name": "S2", "slug": "stripe2-co"})).json()
    oid = uuid.UUID(org["id"])
    await deliver(anon_client, event("checkout.session.completed", checkout_completed(oid)))
    async with session_factory() as s:
        rows = (await s.execute(select(AuditLog).where(AuditLog.action == "billing.stripe_event"))).scalars().all()
    blob = json.dumps([r.detail for r in rows]) + " ".join(str(r.target_id) for r in rows)
    assert "payer@example.com" not in blob and "cus_123" not in blob.replace("evt_", "")
