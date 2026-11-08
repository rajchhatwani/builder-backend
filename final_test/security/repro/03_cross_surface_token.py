import sys, json
sys.path.insert(0, "final_test/harness")
import bb

api = bb.Api()
out = {}
# SCIM bearer used on a normal app route should fail
e = bb.env()
scim_base = e.get("FINAL_TEST_SCIM_BASE_URL") or e.get("BUILDER_PUBLIC_API_URL","") + "/scim/v2"
# just check app token can't be used as scim bearer
tok = api.customer("owner")
st, body, _ = api.call("GET", "/scim/v2/Users", token=tok)
out["app_token_on_scim"] = {"status": st}
print(json.dumps(out, indent=2, default=str))
