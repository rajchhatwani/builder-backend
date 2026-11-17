from lib import *
ST = A.staff("admin")
st = {}
oe, ot = user("uiown"); ae, at = user("uiadm"); me, mt = user("uimem"); xe, xt = user("uiout")
c, org, _ = call(ot, "POST", "/orgs", {"name": "UI Acme " + RUN}); slug, oid = org["slug"], org["id"]
A.call("PATCH", f"/admin/organizations/{oid}/plan", {"plan_id": "team", "reason": "bbf"}, ST)
for e_, t_, r_ in [(ae, at, "admin"), (me, mt, "member")]:
    c, b, _ = call(ot, "POST", f"/orgs/{slug}/invitations", {"email": e_, "role": r_}); call(t_, "POST", "/orgs/invitations/accept", {"token": b["token"]})
for i in range(3):
    c, p, _ = call(ot, "POST", "/projects", {"name": f"UI Project {i} {RUN} <b>x</b> 😀", "organization_id": oid})
    print(c, str(p)[:150]) if c != 201 else None
pid = p["id"]
c, e, _ = call(ot, "POST", f"/projects/{pid}/entities", {"name": "Book"}); call(ot, "POST", f"/entities/{e['id']}/fields", {"name": "title", "type": "string", "required": True})
call(ot, "POST", f"/orgs/{slug}/invitations", {"email": f"pend-{RUN}@dumbpotato.com", "role": "member"})
json.dump({"owner": oe, "admin": ae, "member": me, "outsider": xe, "slug": slug, "oid": oid, "pid": pid, "run": RUN}, open(HERE.parent / "logs" / "ui_state.json", "w"))
print("ok", slug)
