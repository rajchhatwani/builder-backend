import sys, json, time
sys.path.insert(0, "/mnt/files/projects/builder-backend/final_test/harness")
import bb

ORG_ID = "0b24d1cf-01d0-4849-b6d9-79c4307f9e72"  # bb-acme
CUSTOMER = "cus_ft_bbacme_test"
SUB_ID = "sub_ft_bbacme_test"
OTHER_CUSTOMER = "cus_ft_attacker"
OTHER_SUB = "sub_ft_other_org"

out = {}

# 1. Checkout completed: bind this org to a fake Stripe customer/subscription, plan=team
ts0 = int(time.time())
st, body = bb.stripe_webhook(
    "checkout.session.completed",
    {
        "id": "cs_ft_1", "mode": "subscription", "payment_status": "paid",
        "customer": CUSTOMER, "subscription": SUB_ID,
        "client_reference_id": ORG_ID,
        "metadata": {"organization_id": ORG_ID, "plan_id": "team"},
    },
    event_id=f"evt_ft_checkout_{ts0}", timestamp=ts0,
)
out["1_checkout_completed"] = {"status": st, "body": str(body)[:200]}

# 2. Replay the SAME event id -> must be 'duplicate', no second effect
st, body = bb.stripe_webhook(
    "checkout.session.completed",
    {
        "id": "cs_ft_1", "mode": "subscription", "payment_status": "paid",
        "customer": CUSTOMER, "subscription": SUB_ID,
        "client_reference_id": ORG_ID,
        "metadata": {"organization_id": ORG_ID, "plan_id": "team"},
    },
    event_id=f"evt_ft_checkout_{ts0}", timestamp=ts0,  # SAME event id and timestamp as #1
)
out["2_replay_same_event_id"] = {"status": st, "body": str(body)[:200]}

# 3. livemode mismatch: a livemode=true event for this (test-mode) org's real subscription
ts1 = int(time.time())
st, body = bb.stripe_webhook(
    "customer.subscription.updated",
    {"id": SUB_ID, "customer": CUSTOMER, "status": "active",
     "items": {"data": [{"price": {"id": "price_fake"}, "current_period_end": ts1 + 86400}]},
     "current_period_end": ts1 + 86400},
    event_id=f"evt_ft_livemode_{ts1}", timestamp=ts1, livemode=True,
)
out["3_livemode_mismatch"] = {"status": st, "body": str(body)[:250]}

# 4. customer_mismatch: an update for the SAME subscription id but a DIFFERENT stripe customer
ts2 = int(time.time())
st, body = bb.stripe_webhook(
    "customer.subscription.updated",
    {"id": SUB_ID, "customer": OTHER_CUSTOMER, "status": "active",
     "items": {"data": [{"price": {"id": "price_fake"}, "current_period_end": ts2 + 86400}]},
     "current_period_end": ts2 + 86400},
    event_id=f"evt_ft_custmismatch_{ts2}", timestamp=ts2,
)
out["4_customer_mismatch"] = {"status": st, "body": str(body)[:250]}

# 5. other_subscription (out-of-order / stale replacement): an update for a DIFFERENT subscription id
#    with the correct customer, while the org's live subscription is still SUB_ID
ts3 = int(time.time())
st, body = bb.stripe_webhook(
    "customer.subscription.updated",
    {"id": OTHER_SUB, "customer": CUSTOMER, "status": "active",
     "items": {"data": [{"price": {"id": "price_fake"}, "current_period_end": ts3 + 86400}]},
     "current_period_end": ts3 + 86400},
    event_id=f"evt_ft_othersub_{ts3}", timestamp=ts3,
)
out["5_other_subscription"] = {"status": st, "body": str(body)[:250]}

# 6. stale event: an update with a `created` timestamp OLDER than the already-applied checkout event (ts0)
st, body = bb.stripe_webhook(
    "customer.subscription.updated",
    {"id": SUB_ID, "customer": CUSTOMER, "status": "active",
     "items": {"data": [{"price": {"id": "price_fake"}, "current_period_end": ts0 + 100}]},
     "current_period_end": ts0 + 100},
    event_id=f"evt_ft_stale_{ts0-1000}", timestamp=ts0 - 1000,
)
out["6_stale_event"] = {"status": st, "body": str(body)[:250]}

# 7. bad signature on an otherwise-legit, well-formed event -> should be refused before any processing
ts4 = int(time.time())
st, body = bb.stripe_webhook(
    "customer.subscription.updated",
    {"id": SUB_ID, "customer": CUSTOMER, "status": "active",
     "items": {"data": [{"price": {"id": "price_fake"}, "current_period_end": ts4 + 86400}]}},
    event_id=f"evt_ft_badsig_{ts4}", timestamp=ts4, secret="wrong_secret_padding_xxxxxxxxxxxx",
)
out["7_bad_signature"] = {"status": st, "body": str(body)[:200]}

print(json.dumps(out, indent=2, default=str))
with open("/mnt/files/projects/builder-backend/final_test/security/evidence/stripe_webhook_live_results.json", "w") as f:
    json.dump(out, f, indent=2, default=str)
