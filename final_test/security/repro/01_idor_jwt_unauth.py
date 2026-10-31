import sys, json, time
sys.path.insert(0, "final_test/harness")
import bb

api = bb.Api()
out = {}

# 1. Outsider cannot see bb-acme (tenant isolation / IDOR)
try:
    tok_out = api.customer("outsider")
    st, body, _ = api.call("GET", "/orgs/bb-acme", token=tok_out)
    out["outsider_sees_bb_acme"] = {"status": st, "body": str(body)[:200]}
except Exception as e:
    out["outsider_sees_bb_acme"] = {"error": str(e)}

# 2. Unauthenticated access to a guarded route
try:
    st, body, _ = api.call("GET", "/orgs/bb-acme", token=None)
    out["unauth_orgs_bb_acme"] = {"status": st}
except Exception as e:
    out["unauth_orgs_bb_acme"] = {"error": str(e)}

# 3. JWT alg=none / tampering quick check: corrupt a valid token's signature
try:
    tok_owner = api.customer("owner")
    parts = tok_owner.split(".")
    tampered = parts[0] + "." + parts[1] + ".AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    st, body, _ = api.call("GET", "/account/me", token=tampered)
    out["tampered_jwt_sig"] = {"status": st}
except Exception as e:
    out["tampered_jwt_sig"] = {"error": str(e)}

# 4. Stripe webhook forgery: bad signature
try:
    st, body = bb.stripe_webhook(api, "customer.subscription.updated", {"id": "sub_fake", "customer": "cus_fake"}, bad_signature=True)
    out["stripe_bad_sig"] = {"status": st, "body": str(body)[:200]}
except Exception as e:
    out["stripe_bad_sig"] = {"error": str(e)}

print(json.dumps(out, indent=2, default=str))
