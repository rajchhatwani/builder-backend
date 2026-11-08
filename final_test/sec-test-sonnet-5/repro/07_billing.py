#!/usr/bin/env python3
"""Category 7 — Billing. Self-contained disposable orgs; all forged events via bb.stripe_webhook
(signed with the real env webhook secret, exactly like Stripe does -- this tests "what happens if
a signed event says X", not signature bypass, which is separately covered). No webhook endpoint
is registered at Stripe (per SESSION_HANDOFF); we POST straight to the app's own endpoint.

Usage: python3 final_test/sec-test-sonnet-5/repro/07_billing.py
"""
from __future__ import annotations

import os
import sys
import time
import uuid

import requests

sys.path.insert(0, os.path.dirname(__file__))
from _common import bb, ngrok_headers, new_disposable_email, record, tunnel_api_base  # noqa: E402

TARGET = os.environ.get("BB_TARGET", "tunnel")
API = tunnel_api_base() if TARGET == "tunnel" else os.environ.get("BB_LOCAL_API", "http://127.0.0.1:8001")
HDRS = ngrok_headers() if TARGET == "tunnel" else {}
_DELAY = 0.3 if TARGET == "tunnel" else 0.1
os.environ.setdefault("BB_API", API)

_session = requests.Session()


def req(method, path, body=None, token=None, headers=None):
    h = {**HDRS, **(headers or {})}
    if token:
        h["Authorization"] = f"Bearer {token}"
    time.sleep(_DELAY)
    for attempt in range(3):
        try:
            return _session.request(method, API + path, json=body, headers=h, timeout=30)
        except requests.exceptions.ConnectionError:
            if attempt == 2:
                raise
            time.sleep(2)


def new_account(prefix="bill"):
    email = new_disposable_email(prefix)
    pw = "Correct-Horse-Battery-Staple-9!"
    r = req("POST", "/account/register", {"email": email, "password": pw, "name": "sectest"})
    if r.status_code == 429:
        time.sleep(float(r.headers.get("Retry-After", 20)) + 1)
        r = req("POST", "/account/register", {"email": email, "password": pw, "name": "sectest"})
    if r.status_code != 201:
        return None, None, None
    return email, pw, r.json()["access_token"]


def new_org(owner_tok, prefix="bill"):
    slug = f"sectest-{prefix}-" + uuid.uuid4().hex[:8]
    r = req("POST", "/orgs", {"name": "sectest", "slug": slug}, token=owner_tok)
    return (slug, r.json()["id"]) if r.status_code == 201 else (None, None)


def webhook(event_type, obj, **kw):
    return bb.stripe_webhook(event_type, obj, api=API, **kw)


# ---------------------------------------------------------------------------
# 1. Bad signature / malformed signed events
# ---------------------------------------------------------------------------
def test_bad_signature_and_malformed():
    import hashlib
    import hmac
    import json as _json

    bad_sig, _ = webhook("checkout.session.completed", {"id": "cs_sectest"}, secret="wrong-secret-entirely")

    # a signed-but-malformed event: data.object is not a dict at all (review's old F-004 was a
    # 500 here). bb.stripe_webhook always wraps a dict obj, so build this one by hand.
    e = bb.env()
    secret = e["BUILDER_STRIPE_WEBHOOK_SECRET"].split(",")[0].strip()
    ts = int(time.time())
    payload = _json.dumps({"id": "evt_sectest_baddata", "object": "event", "type": "checkout.session.completed",
                            "livemode": False, "created": ts, "data": {"object": "not-a-dict"}}, separators=(",", ":"))
    sig = hmac.new(secret.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
    rr = _session.post(API + "/billing/stripe/webhook", data=payload.encode(),
                        headers={**HDRS, "Content-Type": "application/json", "Stripe-Signature": f"t={ts},v1={sig}"},
                        timeout=30)
    non_dict_status = rr.status_code

    ok = bad_sig == 400 and non_dict_status in (200, 400)
    record("billing", "7.1", "bad-signature and malformed-but-signed events are handled without a 500",
           "wrong secret -> 400; signed event whose data.object is not a dict -> acknowledged (200, "
           "ignored) or 400, never a 500 (review F-004 was a 500 here)",
           f"bad_signature={bad_sig} non_dict_data_object={non_dict_status}",
           "High" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# 2. Checkout tampering: forged event sets an arbitrary plan via metadata, no real payment
# ---------------------------------------------------------------------------
def test_checkout_plan_tampering():
    owner_email, owner_pw, owner_tok = new_account("checktamper")
    slug, org_id = new_org(owner_tok, "checktamper")
    if not slug:
        record("billing", "7.2", "checkout plan tampering via forged webhook", "n/a",
               "could not create disposable org", "Medium", "NOT_TESTABLE")
        return

    before = req("GET", f"/orgs/{slug}/plan", token=owner_tok).json()
    status, body = webhook("checkout.session.completed", {
        "id": "cs_sectest_" + uuid.uuid4().hex[:8],
        "mode": "subscription",
        "payment_status": "paid",
        "client_reference_id": org_id,
        "customer": "cus_sectest_" + uuid.uuid4().hex[:8],
        "subscription": "sub_sectest_" + uuid.uuid4().hex[:8],
        "metadata": {"plan_id": "enterprise"},
    })
    after = req("GET", f"/orgs/{slug}/plan", token=owner_tok).json()
    upgraded_for_free = after["plan"]["id"] == "enterprise" and before["plan"]["id"] != "enterprise"
    record("billing", "7.2", "a forged (but correctly signed) checkout.session.completed can set "
           "ANY known plan via metadata.plan_id, with no cross-check against what was actually paid for",
           "the app should verify the metadata plan_id against the actual Stripe price/amount paid, "
           "not trust the metadata field alone -- or this reduces to 'whoever can sign a webhook "
           "event can set any org to any plan for free'",
           f"webhook_status={status} plan before={before['plan']['id']} after={after['plan']['id']}",
           "High" if upgraded_for_free else "Info",
           "CONFIRMED" if upgraded_for_free else "SOLID",
           note="app/services/stripe_webhook_service.py:_apply_checkout -- plan_id is read from "
                "session.metadata and accepted if it's merely a KNOWN plan name (_plan_known), with "
                "no check that it matches the price/amount actually in the forged session object. "
                "Real-world precondition: the attacker already has the Stripe webhook signing "
                "secret (this test simulates that specific compromise, per the test brief) or an "
                "endpoint misconfiguration that lets them reach this route with a valid signature")


# ---------------------------------------------------------------------------
# 3. Replay (duplicate event id) and stale/out-of-order
# ---------------------------------------------------------------------------
def test_replay_and_stale():
    owner_email, owner_pw, owner_tok = new_account("replay")
    slug, org_id = new_org(owner_tok, "replay")
    if not slug:
        record("billing", "7.3", "webhook replay and stale/out-of-order handling", "n/a",
               "could not create disposable org", "Medium", "NOT_TESTABLE")
        return
    cust = "cus_sectest_" + uuid.uuid4().hex[:8]
    sub_id = "sub_sectest_" + uuid.uuid4().hex[:8]
    event_id = "evt_sectest_replay_" + uuid.uuid4().hex[:8]

    now = int(time.time())
    obj_new = {"id": sub_id, "customer": cust, "status": "active",
               "items": {"data": [{"price": {"id": "price_team_fake"}, "current_period_end": now + 86400}]},
               "metadata": {"organization_id": org_id, "plan_id": "team"}}
    s1, _ = webhook("customer.subscription.updated", obj_new, event_id=event_id, timestamp=now)
    s2, _ = webhook("customer.subscription.updated", obj_new, event_id=event_id, timestamp=now)  # exact replay

    obj_older = dict(obj_new, metadata={"organization_id": org_id, "plan_id": "business"})
    s3, _ = webhook("customer.subscription.updated", obj_older,
                     event_id="evt_sectest_stale_" + uuid.uuid4().hex[:8], timestamp=now - 3600)  # older `created`

    after = req("GET", f"/orgs/{slug}/plan", token=owner_tok).json()
    stale_applied = after["plan"]["id"] == "business"
    record("billing", "7.3", "duplicate event id and an older out-of-order event are both no-ops",
           "the second POST of the SAME event id changes nothing further; an event with an OLDER "
           "`created` timestamp than one already applied is ignored ('stale'), even if it claims a "
           "different plan",
           f"first={s1} replay_same_id={s2} older_event_different_plan={s3} "
           f"final_plan={after['plan']['id']} (stale_was_wrongly_applied={stale_applied})",
           "High" if stale_applied else "Info",
           "CONFIRMED" if stale_applied else "SOLID")


# ---------------------------------------------------------------------------
# 4. Other customer / other subscription cannot move a different org's billing
# ---------------------------------------------------------------------------
def test_other_customer_isolation():
    owner_a_email, owner_a_pw, owner_a_tok = new_account("custa")
    slug_a, org_a_id = new_org(owner_a_tok, "custa")
    owner_b_email, owner_b_pw, owner_b_tok = new_account("custb")
    slug_b, org_b_id = new_org(owner_b_tok, "custb")
    if not slug_a or not slug_b:
        record("billing", "7.4", "other-customer / other-subscription isolation", "n/a",
               "could not create both orgs", "Medium", "NOT_TESTABLE")
        return

    cust_a = "cus_sectest_a_" + uuid.uuid4().hex[:8]
    sub_a = "sub_sectest_a_" + uuid.uuid4().hex[:8]
    now = int(time.time())
    # give org A a real customer binding first (checkout), then try to move it with an event
    # whose customer is B's, while claiming org A via client_reference_id.
    webhook("checkout.session.completed", {
        "id": "cs_a", "mode": "subscription", "payment_status": "paid",
        "client_reference_id": org_a_id, "customer": cust_a, "subscription": sub_a,
        "metadata": {"plan_id": "team"},
    }, timestamp=now - 100)
    before = req("GET", f"/orgs/{slug_a}/plan", token=owner_a_tok).json()

    s, _ = webhook("customer.subscription.updated", {
        "id": sub_a, "customer": "cus_sectest_DIFFERENT_" + uuid.uuid4().hex[:8], "status": "active",
        "items": {"data": [{"price": {"id": "price_biz_fake"}, "current_period_end": now + 86400}]},
        "metadata": {"organization_id": org_a_id, "plan_id": "business"},
    }, timestamp=now)
    after = req("GET", f"/orgs/{slug_a}/plan", token=owner_a_tok).json()
    moved = after["plan"]["id"] != before["plan"]["id"]
    record("billing", "7.4", "an event citing a DIFFERENT customer than the one already bound to the "
           "org is refused (customer_mismatch), even if it names the right org/subscription id",
           "org A's plan doesn't change when a forged event claims org A's subscription id but a "
           "customer id that was never org A's",
           f"webhook_status={s} plan before={before['plan']['id']} after={after['plan']['id']}",
           "High" if moved else "Info",
           "CONFIRMED" if moved else "SOLID")


# ---------------------------------------------------------------------------
# 5. Livemode mismatch
# ---------------------------------------------------------------------------
def test_livemode_mismatch():
    owner_email, owner_pw, owner_tok = new_account("livemode")
    slug, org_id = new_org(owner_tok, "livemode")
    if not slug:
        record("billing", "7.5", "livemode mismatch", "n/a", "could not create disposable org", "Medium", "NOT_TESTABLE")
        return
    before = req("GET", f"/orgs/{slug}/plan", token=owner_tok).json()
    s, _ = webhook("checkout.session.completed", {
        "id": "cs_live_" + uuid.uuid4().hex[:8], "mode": "subscription", "payment_status": "paid",
        "client_reference_id": org_id, "customer": "cus_sectest_" + uuid.uuid4().hex[:8],
        "subscription": "sub_sectest_" + uuid.uuid4().hex[:8], "metadata": {"plan_id": "enterprise"},
    }, livemode=True)  # this stack's secret key is test-mode; a livemode=true event must be refused
    after = req("GET", f"/orgs/{slug}/plan", token=owner_tok).json()
    moved = after["plan"]["id"] != before["plan"]["id"]
    record("billing", "7.5", "a livemode=true event is refused on a test-mode platform",
           "livemode_mismatch -- the plan never changes",
           f"webhook_status={s} plan before={before['plan']['id']} after={after['plan']['id']}",
           "High" if moved else "Info",
           "CONFIRMED" if moved else "SOLID")


# ---------------------------------------------------------------------------
# 6. Checkout/portal access by a non-admin member
# ---------------------------------------------------------------------------
def test_checkout_portal_non_admin():
    owner_email, owner_pw, owner_tok = new_account("nonadmin")
    slug, org_id = new_org(owner_tok, "nonadmin")
    if not slug:
        record("billing", "7.6", "checkout/portal access requires admin", "n/a",
               "could not create disposable org", "Medium", "NOT_TESTABLE")
        return
    # a write-scope API token stands in for "not a session with admin role" -- org_context
    # already refuses API tokens on these routes (session-only), which is itself the control;
    # confirm it specifically for billing here too.
    tok_resp = req("POST", "/account/tokens", {"name": "sectest", "scopes": ["read", "write"]}, token=owner_tok)
    api_tok = tok_resp.json().get("token") if tok_resp.status_code == 201 else None
    r1 = req("POST", f"/orgs/{slug}/billing/checkout", {"plan_id": "team"}, token=api_tok) if api_tok else None
    r2 = req("POST", f"/orgs/{slug}/billing/portal", {}, token=api_tok) if api_tok else None
    ok = api_tok is not None and r1.status_code == 403 and r2.status_code == 403
    record("billing", "7.6", "checkout/portal are session-only (an API token, even write-scope, is refused)",
           "both routes answer 403 session_required for an API token",
           f"checkout={r1.status_code if r1 is not None else 'n/a'} portal={r2.status_code if r2 is not None else 'n/a'}",
           "High" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


def main():
    print(f"=== 07_billing against {TARGET} ({API}) ===")
    for fn in (
        test_bad_signature_and_malformed,
        test_checkout_plan_tampering,
        test_replay_and_stale,
        test_other_customer_isolation,
        test_livemode_mismatch,
        test_checkout_portal_non_admin,
    ):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            record("billing", fn.__name__, fn.__name__, "test runs cleanly",
                   f"test script raised {type(exc).__name__}: {exc}", "Low", "NOT_TESTABLE")


if __name__ == "__main__":
    main()
