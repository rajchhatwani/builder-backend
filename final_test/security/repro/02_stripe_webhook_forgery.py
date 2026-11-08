import sys, json, time
sys.path.insert(0, "final_test/harness")
import bb

out = {}
# bad signature
st, body = bb.stripe_webhook("customer.subscription.updated", {"id": "sub_fake", "customer": "cus_fake"}, secret="wrong_secret_xxxxxxxxxxxxxxxxxxxx")
out["bad_signature"] = {"status": st, "body": str(body)[:200]}

# stale timestamp (> 5 min old, typical Stripe tolerance)
st, body = bb.stripe_webhook("customer.subscription.updated", {"id": "sub_fake2", "customer": "cus_fake2"}, timestamp=int(time.time()) - 3600)
out["stale_timestamp"] = {"status": st, "body": str(body)[:200]}

# livemode true (should be refused in test env)
st, body = bb.stripe_webhook("customer.subscription.updated", {"id": "sub_fake3", "customer": "cus_fake3"}, livemode=True)
out["livemode_true"] = {"status": st, "body": str(body)[:200]}

# replay: send the same valid event twice
eid = f"evt_replaytest_{int(time.time())}"
st1, b1 = bb.stripe_webhook("customer.subscription.updated", {"id": "sub_replay", "customer": "cus_replay", "status":"active"}, event_id=eid)
st2, b2 = bb.stripe_webhook("customer.subscription.updated", {"id": "sub_replay", "customer": "cus_replay", "status":"active"}, event_id=eid)
out["replay_same_event_id"] = {"first": st1, "second": st2, "second_body": str(b2)[:200]}

print(json.dumps(out, indent=2, default=str))
