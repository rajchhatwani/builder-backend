import sys, json, time, hmac, hashlib, os, urllib.request, urllib.error
sys.path.insert(0, "/mnt/files/projects/builder-backend/final_test/harness")
import bb

e = bb.env()
secret = e["BUILDER_STRIPE_WEBHOOK_SECRET"].split(",")[0].strip()
API = "http://127.0.0.1:8000"
ORG_ID = "0b24d1cf-01d0-4849-b6d9-79c4307f9e72"
CUSTOMER = "cus_ft_bbacme_test"
SUB_ID = "sub_ft_bbacme_test"

def post(created_field_ts, event_id):
    now_sig_ts = int(time.time())  # keep the signature timestamp fresh/valid
    payload = json.dumps({
        "id": event_id, "object": "event", "type": "customer.subscription.updated",
        "livemode": False, "created": created_field_ts,
        "data": {"object": {"id": SUB_ID, "customer": CUSTOMER, "status": "active",
                             "items": {"data": [{"price": {"id": "price_fake"},
                                                  "current_period_end": created_field_ts + 86400}]},
                             "current_period_end": created_field_ts + 86400}},
    }, separators=(",", ":"))
    sig = hmac.new(secret.encode(), f"{now_sig_ts}.{payload}".encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(API + "/billing/stripe/webhook", payload.encode(),
                                  {"Content-Type": "application/json", "Stripe-Signature": f"t={now_sig_ts},v1={sig}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read()[:200]
    except urllib.error.HTTPError as ex:
        return ex.code, ex.read()[:200]

# first, apply a fresh/current update so there is a "newest_applied" to be stale against
now = int(time.time())
st1, b1 = post(now, f"evt_ft_fresh_{now}")
print("fresh update ->", st1, b1)

# now send one with an OLDER `created` field but a current, valid signature timestamp
st2, b2 = post(now - 5000, f"evt_ft_stale_{now}_older")
print("stale (older created, fresh signature) ->", st2, b2)

with open("/mnt/files/projects/builder-backend/final_test/security/evidence/stripe_stale_result.json", "w") as f:
    json.dump({"fresh_update": {"status": st1, "body": str(b1)}, "stale_update": {"status": st2, "body": str(b2)}}, f, indent=2)
