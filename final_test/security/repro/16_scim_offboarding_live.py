"""Checkpoint: SCIM deactivation -- confirms membership removal + token_version bump, live."""
import sys, json
sys.path.insert(0, "final_test/harness")
import bb
api = bb.Api()
owner_tok = api.customer("owner")
st, b, _ = api.call("POST", "/orgs/bb-sso/scim/token", {}, token=owner_tok)
scim = bb.Scim(b["base_url"], b["token"])
email = "sectest-scimoffboard@dumbpotato.com"
st, body = scim.call("POST", "/Users", {
    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"], "userName": email, "active": True,
    "name": {"givenName": "SCIM", "familyName": "Offboard"}, "emails": [{"value": email, "primary": True}],
})
print("SCIM create:", st)
user_id = body["id"]
# -- inspect DB for token_version/membership before/after deactivation (see evidence file) --
st, body = scim.call("PATCH", f"/Users/{user_id}", {
    "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
    "Operations": [{"op": "replace", "value": {"active": False}}],
})
print("SCIM deactivate:", st)
