from lib import *
from urllib.parse import quote as q
ow = A.login("bb-owner@dumbpotato.com", PW); assert ow
ST = A.staff("admin")
c, b, _ = call(ow, "POST", "/orgs/bb-sso/scim/token"); tk = b["token"]
rec("J9.01", "owner issues SCIM token, shown once, hint afterwards", bool(tk) and "token" not in call(ow, "GET", "/orgs/bb-sso/scim")[1], "")
S = bb.Scim(A.base + "/scim/v2", tk)
bad = bb.Scim(A.base + "/scim/v2", "bad" + tk[3:])
c, b = bad.call("GET", "/Users"); rec("J9.02", "wrong SCIM token 401", c == 401, f"{c}")
c, b = bb.Scim(A.base + "/scim/v2", "").call("GET", "/Users"); rec("J9.03", "empty bearer 401", c == 401, f"{c}")
c, b = S.call("GET", "/ServiceProviderConfig"); rec("J9.04", "ServiceProviderConfig", c == 200 and "patch" in json.dumps(b).lower(), f"{c}")
for p in ("/ResourceTypes", "/Schemas", "/Users", "/Groups"):
    c, b = S.call("GET", p); rec("J9.05", f"GET {p}", c == 200, f"{c}")
c, b = S.call("GET", "/Users/not-a-uuid"); rec("J9.06", "unknown/malformed user id 404 not 500", c in (404, 400), f"{c}")
em = f"scim-{RUN}@dumbpotato.com"
body = {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"], "userName": em, "name": {"givenName": "Sc", "familyName": "Im"}, "emails": [{"value": em, "primary": True}], "active": True, "externalId": "ext-" + RUN}
c, u = S.call("POST", "/Users", body); rec("J9.10", "create user 201", c == 201, f"{c} {json.dumps(u)[:200]}"); uid = u.get("id")
c, u2 = S.call("POST", "/Users", body); rec("J9.11", "duplicate userName 409", c == 409, f"{c}")
c, b = S.call("POST", "/Users", {**body, "userName": "x@gmail.com", "emails": [{"value": "x@gmail.com", "primary": True}]}); rec("J9.12", "user outside verified domain refused", c in (400, 403, 409, 422), f"{c} {json.dumps(b)[:150]}")
c, b = S.call("POST", "/Users", {**body, "userName": "nodomain"}); rec("J9.13", "userName without e-mail 4xx", 400 <= c < 500, f"{c}")
c, b = S.call("POST", "/Users", {"schemas": []}); rec("J9.14", "empty create body 4xx not 500", 400 <= c < 500, f"{c}")
c, b = S.call("GET", "/Users?filter=" + q(f'userName eq "{em}"')); rec("J9.15", "filter userName eq", c == 200 and b.get("totalResults") == 1, f"{c} {b.get('totalResults')}")
c, b = S.call("GET", "/Users?filter=userName%20co%20%22%27%3B%20DROP"); rec("J9.16", "weird filter 4xx not 500", c < 500, f"{c}")
c, b = S.call("GET", "/Users?count=1&startIndex=1"); rec("J9.17", "pagination count=1", c == 200 and len(b.get("Resources", [])) <= 1, f"{c}")
c, b = S.call("GET", "/Users?count=100000&startIndex=-5"); rec("J9.18", "pagination absurd values clamped", c < 500, f"{c}")
c, b = S.call("GET", f"/Users/{uid}"); rec("J9.19", "get user", c == 200 and b.get("userName") == em, f"{c}")
# the account exists & is a member
c, b, _ = call(ow, "GET", "/orgs/bb-sso/members"); mem = [m for m in b["items"] if m["email"] == em]
rec("J9.20", "SCIM user appears in org members, role member", bool(mem) and mem[0]["role"] == "member", json.dumps(mem)[:200])
c, b, _ = call(ow, "GET", "/orgs/bb-sso/plan"); seats0 = b["usage"]["seats_used"]
# groups
c, gl = S.call("GET", "/Groups"); gid = next((x["id"] for x in gl.get("Resources", []) if x["displayName"] == "bb-test-admins"), None)
if not gid:
    c, g = S.call("POST", "/Groups", {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"], "displayName": "bb-test-admins", "members": []}); gid = g["id"]
c, g = S.call("PATCH", f"/Groups/{gid}", {"schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"], "Operations": [{"op": "add", "path": "members", "value": [{"value": uid}]}]}); rec("J9.30", "group PATCH add member", c == 200, f"{c} {json.dumps(g)[:150]}")
c, b, _ = call(ow, "GET", "/orgs/bb-sso/members"); mem = [m for m in b["items"] if m["email"] == em]; rec("J9.31", "mapped group (bb-test-admins) sets role admin", bool(mem) and mem[0]["role"] == "admin", json.dumps(mem)[:200])
c, b = S.call("PATCH", f"/Groups/{gid}", {"schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"], "Operations": [{"op": "remove", "path": f'members[value eq "{uid}"]'}]}); rec("J9.32", "group patch remove member", c in (200, 204), f"{c}")
c, b, _ = call(ow, "GET", "/orgs/bb-sso/members"); mem = [m for m in b["items"] if m["email"] == em]; rec("J9.33", "removal from mapped group reverts role to member", bool(mem) and mem[0]["role"] == "member", json.dumps(mem)[:150])
# owner mapping rule: only an Owner may map a group to Owner; an Admin may not
ae_, at_ = user("sadm")
c, b, _ = call(ow, "POST", "/orgs/bb-sso/invitations", {"email": ae_, "role": "admin"}); c, b2, _ = call(at_, "POST", "/orgs/invitations/accept", {"token": b["token"]})
c, b, _ = call(at_, "PATCH", "/orgs/bb-sso/scim", {"group_roles": {"bb-test-owners": "owner"}}); rec("J9.34", "an Admin cannot map a group to Owner", c in (403, 409, 422), f"{c} {json.dumps(b)[:150]}")
c, b, _ = call(ow, "PATCH", "/orgs/bb-sso/scim", {"group_roles": {"bb-test-owners": "owner", "bb-test-admins": "admin"}}); rec("J9.35", "an Owner may map a group to Owner", c == 200, f"{c}")
c, b, _ = call(ow, "PATCH", "/orgs/bb-sso/scim", {"group_roles": {"bb-test-admins": "admin"}}); rec("J9.36", "restore original mapping", c == 200, f"{c}")
c, b, _ = call(ow, "DELETE", f"/orgs/bb-sso/members/{call(ow,'GET','/orgs/bb-sso/members')[1]['items'][0]['user_id']}") if False else (0, 0, 0)
# update / deactivate
c, b = S.call("PUT", f"/Users/{uid}", {**body, "name": {"givenName": "New", "familyName": "Name"}}); rec("J9.40", "PUT user", c == 200, f"{c}")
c, b = S.call("PATCH", f"/Users/{uid}", {"schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"], "Operations": [{"op": "replace", "path": "active", "value": False}]}); rec("J9.41", "PATCH active=false deactivates", c == 200 and b.get("active") is False, f"{c}")
c, b, _ = A.call("POST", "/account/login", {"email": em, "password": PW}); rec("J9.42", "deactivated user cannot log in", c in (401, 403), f"{c}")
c, b, _ = call(ow, "GET", "/orgs/bb-sso/plan"); rec("J9.43", "seat freed after deactivation (seats_used decreased)", b["usage"]["seats_used"] < seats0 or seats0 == 0, f"{seats0} -> {b['usage']['seats_used']}")
c, b = S.call("PATCH", f"/Users/{uid}", {"schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"], "Operations": [{"op": "replace", "value": {"active": True}}]}); rec("J9.44", "reactivate (no-path replace, Azure/Okta style)", c == 200 and b.get("active") is True, f"{c} {json.dumps(b)[:120]}")
c, b = S.call("PATCH", f"/Users/{uid}", {"schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"], "Operations": [{"op": "bogus", "path": "x"}]}); rec("J9.45", "invalid PATCH op 4xx", 400 <= c < 500, f"{c}")
c, b = S.call("PATCH", f"/Users/{uid}", {"Operations": [{"op": "replace", "path": "userName", "value": "other@gmail.com"}]}); rec("J9.46", "userName change to a foreign domain refused", c in (400, 403, 409, 422), f"{c}")
# owner can never be touched
c, b = S.call("GET", '/Users?filter=' + q('userName eq "bb-owner@dumbpotato.com"')); oid_ = (b.get("Resources") or [{}])[0].get("id")
if oid_:
    c, b = S.call("PATCH", f"/Users/{oid_}", {"schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"], "Operations": [{"op": "replace", "path": "active", "value": False}]}); rec("J9.47", "IdP cannot deactivate the org owner", c in (400, 403, 409), f"{c} {json.dumps(b)[:150]}")
    c, b = S.call("DELETE", f"/Users/{oid_}"); rec("J9.48", "IdP cannot delete the org owner", c in (400, 403, 409), f"{c}")
else: rec("J9.47", "owner is not exposed via SCIM (no match)", True, "owner not linked to SCIM; n/a")
# offboarding side effects: token + project handover
c, b, _ = A.call("POST", "/account/login", {"email": "x", "password": "y"})
c, b = S.call("DELETE", f"/Users/{uid}"); rec("J9.50", "DELETE user", c in (200, 204), f"{c}")
c, b = S.call("GET", f"/Users/{uid}"); rec("J9.51", "deleted user gone/inactive", c == 404 or b.get("active") is False, f"{c}")
# audit
c, b, _ = call(ow, "GET", "/orgs/bb-sso/audit?limit=30"); rec("J9.60", "audit has scim entries", any("scim" in i["action"] for i in b["items"]), ",".join(sorted({i["action"] for i in b["items"]})[:8]))
# plan flag: scim token on team org
# rotate
c, b, _ = call(ow, "POST", "/orgs/bb-sso/scim/token"); tk2 = b["token"]
c, b = S.call("GET", "/Users"); rec("J9.70", "rotating invalidates the old token", c == 401, f"{c}")
S2 = bb.Scim(A.base + "/scim/v2", tk2); c, b = S2.call("GET", "/Users"); rec("J9.71", "new token works", c == 200, f"{c}")
c, b, _ = A.call("POST", f"/admin/organizations/{'2a728b97-4179-4fa3-a8a7-3a56f65c664f'}/scim/rotate", {"reason": "bbf"}, ST); rec("J9.72", "operator rotate", c == 200, f"{c}")
c, b = S2.call("GET", "/Users"); rec("J9.73", "operator rotate kills the owner's token", c == 401, f"{c}")
c, b, _ = call(ow, "POST", "/orgs/bb-sso/scim/token"); tk3 = b["token"]; c, b = bb.Scim(A.base + "/scim/v2", tk3).call("GET", "/Users"); rec("J9.74", "fresh token after operator rotate works", c == 200, f"{c}")
c, b, _ = call(ow, "PATCH", "/orgs/bb-sso/scim", {"active": False}); c2, b2 = bb.Scim(A.base + "/scim/v2", tk3).call("GET", "/Users"); rec("J9.75", "disabled SCIM refuses calls", c2 in (401, 403), f"{c} {c2}")
call(ow, "PATCH", "/orgs/bb-sso/scim", {"active": True})
# member/admin cannot manage
mem_t = user("scm")[1]; c, b, _ = call(mem_t, "POST", "/orgs/bb-sso/scim/token"); rec("J9.76", "outsider cannot mint SCIM token", c in (403, 404), f"{c}")
