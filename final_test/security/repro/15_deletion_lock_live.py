"""Checkpoint: org deletion grace-period lock, live -- create/invite/rename while locked."""
import sys
sys.path.insert(0, "final_test/harness")
import bb
api = bb.Api()
tok = api.customer("owner")
st, b, _ = api.call("POST", "/orgs", {"name": "BB Delete Test", "slug": "bb-delete-live"}, token=tok)
org_id = b["id"]
print("create org:", st)
st, b, _ = api.call("DELETE", "/orgs/bb-delete-live", token=tok)
print("request deletion:", st)
st, b, _ = api.call("POST", "/projects", {"name": "Sneak In", "slug": "sneak-in", "organization_id": org_id}, token=tok)
print("create project while locked (expect 423):", st)
st, b, _ = api.call("POST", "/orgs/bb-delete-live/invitations", {"email": "sneaky@dumbpotato.com", "role": "member"}, token=tok)
print("invite while locked (expect 423):", st)
st, b, _ = api.call("PATCH", "/orgs/bb-delete-live", {"name": "renamed while locked"}, token=tok)
print("rename while locked (expect 423):", st)
st, b, _ = api.call("GET", "/orgs/bb-delete-live", token=tok)
print("read while locked (expect 200, allowed):", st)
st, b, _ = api.call("POST", "/orgs/bb-delete-live/deletion/cancel", {}, token=tok)
print("cancel deletion (expect 200):", st)
st, b, _ = api.call("POST", "/projects", {"name": "After Cancel", "slug": "after-cancel", "organization_id": org_id}, token=tok)
print("create project after cancel (expect 201):", st)
