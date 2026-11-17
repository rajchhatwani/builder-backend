from lib import *
import concurrent.futures as cf
ST = A.staff("admin")
def set_plan(org_id, plan, reason="bbf test"):
    return A.call("PATCH", f"/admin/organizations/{org_id}/plan", {"plan_id": plan, "reason": reason}, ST)

oe, ot = user("own"); ae, at = user("adm"); me, mt = user("mem"); xe, xt = user("out")
# --- J5 org create / rename
c,b,h = call(ot,"POST","/orgs",{"name":"BBF Acme "+RUN}); expect("J5.01","create team org",(c,b,h),201)
org=b; slug=org["slug"]; oid=org["id"]
rec("J5.02","creator is owner, kind=team",org["my_role"]=="owner" and org["kind"]=="team",json.dumps(org)[:200])
c,b,h = call(ot,"POST","/orgs",{"name":"BBF Acme "+RUN,"slug":slug}); expect("J5.03","duplicate slug 409",(c,b,h),409)
for nm in ["","x"*101,"<b>x</b>","😀 emoji org","  ","a\u0000b"]:
    c,b,h = call(ot,"POST","/orgs",{"name":nm}); rec("J5.04","org name %r handled, no 5xx"%nm[:20],c<500,f"HTTP {c} {json.dumps(b)[:120]}")
for sl in ["Admin","a","-x-","api","orgs","admin","../x","x"*200]:
    c,b,h = call(ot,"POST","/orgs",{"name":"S "+RUN,"slug":sl}); rec("J5.05","slug %r handled, no 5xx"%sl[:20],c<500,f"HTTP {c} {json.dumps(b)[:120]}")
c,b,h = call(ot,"PATCH",f"/orgs/{slug}",{"name":"Renamed "+RUN}); expect("J5.06","rename",(c,b,h),200)
c,b,h = call(xt,"PATCH",f"/orgs/{slug}",{"name":"hack"}); expect("J5.07","outsider cannot rename (404/403)",(c,b,h),[403,404])
c,b,h = call(xt,"GET",f"/orgs/{slug}"); expect("J5.08","outsider GET org 404/403, not 200",(c,b,h),[403,404])
c,b,h = A.call("GET",f"/orgs/{slug}"); expect("J5.09","anonymous GET org 401",(c,b,h),401)
# --- plan: new team org plan?
c,b,h = call(ot,"GET",f"/orgs/{slug}/plan"); print("new team org plan:",json.dumps(b)[:400])
plan0=b.get("plan",{}).get("id") or b.get("subscription",{}).get("plan_id")
rec("J6.00","new team org starts on",True,str(plan0))
# invite on free plan (1 seat)
c,b,h = call(ot,"POST",f"/orgs/{slug}/invitations",{"email":ae,"role":"admin"}); 
rec("J6.01","free plan (1 seat): invite refused with 402 mentioning seats",c==402 and "seat" in json.dumps(b).lower(),f"HTTP {c} {json.dumps(b)[:300]}")
c,b,h = set_plan(oid,"team"); expect("J6.02","operator sets team plan",(c,b,h),200)
c,b,h = call(ot,"POST",f"/orgs/{slug}/invitations",{"email":ae,"role":"admin"}); expect("J5.10","invite admin",(c,b,h),201)
inv_a=b; 
rec("J5.11","invite token + url shown once",bool(b.get("token")) and "invite" in b.get("invite_url",""),redact(json.dumps(b)))
rec("J5.12","emailed flag true (mail sink)",b.get("emailed") is True,str(b.get("emailed")))
mail = bb.wait_mail(to=ae, subject="", timeout=20)
rec("J5.13","invitation mail reaches the sink",bool(mail),"")
c,b,h = call(ot,"POST",f"/orgs/{slug}/invitations",{"email":ae,"role":"admin"}); expect("J5.14","duplicate pending invite -> 409 (or idempotent)",(c,b,h),[409,200,201])
c,b,h = call(ot,"POST",f"/orgs/{slug}/invitations",{"email":"not-an-email","role":"member"}); expect("J5.15","bad invite e-mail 422",(c,b,h),[400,422])
c,b,h = call(ot,"POST",f"/orgs/{slug}/invitations",{"email":me,"role":"owner"}); rec("J5.16","invite as owner accepted or refused cleanly",c in(201,400,403,422),f"HTTP {c} {json.dumps(b)[:150]}")
if c==201: call(ot,"DELETE",f"/orgs/{slug}/invitations/{b['id']}")
# wrong account accepts
c,b,h = call(xt,"POST","/orgs/invitations/accept",{"token":inv_a["token"]}); expect("J5.20","wrong account cannot accept invite",(c,b,h),[403,404,409])
c,b,h = call(at,"POST","/orgs/invitations/accept",{"token":"x"*20}); expect("J5.21","bogus token refused",(c,b,h),[400,404,410])
c,b,h = call(at,"GET","/orgs/invitations/pending"); rec("J5.22","pending list shows the invite",c==200 and any(i["organization_slug"]==slug for i in b.get("items",b)),json.dumps(b)[:200])
c,b,h = call(at,"POST","/orgs/invitations/accept",{"token":inv_a["token"]}); expect("J5.23","right account accepts by token",(c,b,h),[200,201])
c,b,h = call(at,"POST","/orgs/invitations/accept",{"token":inv_a["token"]}); expect("J5.24","accept twice refused",(c,b,h),[400,404,409,410])
c,b,h = call(ot,"GET",f"/orgs/{slug}/members"); rec("J5.25","admin listed as member",any(m["email"]==ae and m["role"]=="admin" for m in b.get("items",b)),json.dumps(b)[:300])
# accept by id
c,b,h = call(ot,"POST",f"/orgs/{slug}/invitations",{"email":me,"role":"member"}); inv_m=b
c,b,h = call(mt,"POST",f"/orgs/invitations/{inv_m['id']}/accept"); rec("J5.26","accept by id for an e-mail-unverified account is refused with email_not_verified (design)",c==403 and b.get("code")=="email_not_verified",f"HTTP {c} {json.dumps(b)[:150]}")
c,b,h = call(mt,"POST","/orgs/invitations/accept",{"token":inv_m["token"]}); expect("J5.26b","accept by token (proves mailbox ownership)",(c,b,h),[200,201])
# revoke / expired / resend
c,b,h = call(ot,"POST",f"/orgs/{slug}/invitations",{"email":"rev-%s@dumbpotato.com"%RUN,"role":"member"}); rv=b
c,b,h = call(ot,"POST",f"/orgs/{slug}/invitations/{rv['id']}/resend"); expect("J5.27","resend invite",(c,b,h),[200,201])
rec("J5.27b","resend gives new token/url or not (record)",True,"token_changed=%s"%(b.get("token")!=rv.get("token")))
tok_new=b.get("token")
c,b,h = call(ot,"DELETE",f"/orgs/{slug}/invitations/{rv['id']}"); expect("J5.28","revoke invite",(c,b,h),[200,204])
c,b,h = call(ot,"POST","/orgs/invitations/accept",{"token":tok_new or rv["token"]}); expect("J5.29","revoked token refused",(c,b,h),[400,403,404,409,410])
# --- roles & permissions
c,b,h = call(mt,"POST",f"/orgs/{slug}/invitations",{"email":"z%s@dumbpotato.com"%RUN,"role":"member"}); expect("J5.30","member cannot invite",(c,b,h),403)
c,b,h = call(mt,"PATCH",f"/orgs/{slug}",{"name":"m"}); expect("J5.31","member cannot rename",(c,b,h),403)
c,b,h = call(mt,"GET",f"/orgs/{slug}/members"); expect("J5.32","member can list members",(c,b,h),200)
c,b,h = call(mt,"GET",f"/orgs/{slug}/audit"); rec("J5.33","member audit access",c in(200,403),f"HTTP {c}")
c,b,h = call(mt,"GET",f"/orgs/{slug}/policies"); rec("J5.34","member can read policies (read-only)",c==200,f"HTTP {c}")
c,b,h = call(mt,"PATCH",f"/orgs/{slug}/policies",{"require_mfa":True}); expect("J5.35","member cannot change policies",(c,b,h),403)
c,b,h = call(at,"PATCH",f"/orgs/{slug}/policies",{"session_ttl_hours":0}); expect("J5.36","session ttl 0 refused",(c,b,h),[400,422])
c,b,h = call(at,"PATCH",f"/orgs/{slug}/policies",{"session_ttl_hours":721}); expect("J5.37","session ttl 721 refused",(c,b,h),[400,422])
c,b,h = call(at,"PATCH",f"/orgs/{slug}/policies",{"require_mfa":True}); rec("J5.38","admin can set policy (or only owner)",c in(200,403),f"HTTP {c} {json.dumps(b)[:150]}")
c,b,h = call(ot,"GET",f"/orgs/{slug}/members"); ms={m["email"]:m for m in b.get("items",b)}
aid=ms[ae]["user_id"]; mid=ms[me]["user_id"]; oidu=ms[oe]["user_id"]
c,b,h = call(at,"PATCH",f"/orgs/{slug}/members/{mid}",{"role":"admin"}); rec("J5.40","admin promotes member to admin",c in(200,403),f"HTTP {c}")
c,b,h = call(at,"PATCH",f"/orgs/{slug}/members/{oidu}",{"role":"member"}); expect("J5.41","admin cannot demote owner",(c,b,h),[403,409])
c,b,h = call(at,"PATCH",f"/orgs/{slug}/members/{aid}",{"role":"owner"}); expect("J5.42","admin cannot self-promote to owner",(c,b,h),[403,409])
c,b,h = call(ot,"PATCH",f"/orgs/{slug}/members/{oidu}",{"role":"member"}); expect("J5.43","last owner cannot be demoted",(c,b,h),[400,403,409])
c,b,h = call(ot,"DELETE",f"/orgs/{slug}/members/{oidu}"); expect("J5.44","last owner cannot leave",(c,b,h),[400,403,409])
c,b,h = call(at,"DELETE",f"/orgs/{slug}/members/{oidu}"); expect("J5.45","admin cannot remove owner",(c,b,h),[403,409])
c,b,h = call(ot,"PATCH",f"/orgs/{slug}/members/{mid}",{"role":"bogus"}); expect("J5.46","bogus role 422",(c,b,h),[400,422])
# transfer
c,b,h = call(at,"POST",f"/orgs/{slug}/transfer?to_user_id={aid}"); expect("J5.50","non-owner cannot transfer",(c,b,h),[403])
c,b,h = call(ot,"POST",f"/orgs/{slug}/transfer?to_user_id={uuid.uuid4()}"); expect("J5.51","transfer to non-member refused",(c,b,h),[400,404,409])
c,b,h = call(ot,"POST",f"/orgs/{slug}/transfer?to_user_id={aid}"); expect("J5.52","owner transfers ownership to admin",(c,b,h),[200,204]); 
c,b,h = call(ot,"GET",f"/orgs/{slug}/members"); ms={m["email"]:m for m in b.get("items",b)}
rec("J5.53","roles after transfer: admin->owner, old owner->admin",ms[ae]["role"]=="owner" and ms[oe]["role"]=="admin",f"{ms[ae]['role']} {ms[oe]['role']}")
# swap back
call(at,"POST",f"/orgs/{slug}/transfer?to_user_id={oidu}")
# member leaves
c,b,h = call(mt,"DELETE",f"/orgs/{slug}/members/{mid}"); expect("J5.55","member leaves",(c,b,h),[200,204])
c,b,h = call(mt,"GET",f"/orgs/{slug}"); expect("J5.56","left member loses access",(c,b,h),[403,404])
# audit
c,b,h = call(ot,"GET",f"/orgs/{slug}/audit?limit=5"); rec("J5.60","audit paginates & has entries",c==200 and len(b.get("items",[]))>0,json.dumps(b)[:200])
c,b,h = call(ot,"GET",f"/orgs/{slug}/audit?limit=100000"); rec("J5.61","audit limit huge clamped/422 not 500",c<500,f"HTTP {c}")
c,b,h = call(ot,"GET",f"/orgs/{slug}/audit?limit=-1"); rec("J5.62","audit negative limit 422 not 500",c<500,f"HTTP {c}")

# --- J6 quotas (team: 5 seats, 10 projects, 20 api tokens)
c,b,h = call(ot,"GET",f"/orgs/{slug}/plan"); usage=b.get("usage"); print("usage",usage)
# fill seats incl pending: members now owner+admin=2; pending invites count
res=[]
for i in range(6):
    c,b,h = call(ot,"POST",f"/orgs/{slug}/invitations",{"email":f"seat{i}-{RUN}@dumbpotato.com","role":"member"}); res.append((c, "seat" in json.dumps(b).lower()))
n_ok=sum(1 for c,_ in res if c==201)
rec("J6.10","seats: pending invites count toward 5-seat cap (2 members + pending invites; cap 5 -> 402)",n_ok==2 and res[2][0]==402 and res[3][1],str(res))
# concurrency for last slot: free one seat then race 4 invites
c,b,h=call(ot,"GET",f"/orgs/{slug}/invitations"); inv=[i for i in b.get("items",b) if i["status"]=="pending" and i["email"].startswith("seat")]
assert inv, b
call(ot,"DELETE",f"/orgs/{slug}/invitations/{inv[0]['id']}")
def race(i): return call(ot,"POST",f"/orgs/{slug}/invitations",{"email":f"race{i}-{RUN}@dumbpotato.com","role":"member"})[0]
with cf.ThreadPoolExecutor(6) as ex: codes=list(ex.map(race,range(6)))
rec("J6.11","race for last seat: exactly one invite succeeds",codes.count(201)==1,str(codes))
# projects
pcodes=[]
for i in range(12):
    c,b,h = call(ot,"POST","/projects",{"name":f"P{i}-{RUN}","organization_id":oid}); pcodes.append(c)
    if c==402: pj402=b; break
rec("J6.20","projects: 10 ok then 402 naming projects",pcodes.count(201)==10 and pcodes[-1]==402 and "project" in json.dumps(pj402).lower(),str(pcodes)+json.dumps(pj402)[:200])
def racep(i): return call(ot,"POST","/projects",{"name":f"R{i}-{RUN}","organization_id":oid})[0]
c,b,h = call(ot,"GET",f"/projects"); items=b.get("items",b)
mine=[p for p in items if p["organization_id"]==oid]
call(ot,"DELETE",f"/projects/{mine[0]['id']}")
with cf.ThreadPoolExecutor(6) as ex: codes=list(ex.map(racep,range(6)))
rec("J6.21","race for last project slot: exactly one succeeds",codes.count(201)==1,str(codes))
# downgrade over limit
c,b,h = set_plan(oid,"free"); rec("J6.30","downgrade team->free while over limits: refused or allowed w/ read-only (record)",True,f"HTTP {c} {json.dumps(b)[:200]}")
c,b,h = call(ot,"POST","/projects",{"name":"afterdown-"+RUN,"organization_id":oid}); rec("J6.31","after downgrade-over-limit new project blocked 402",c==402,f"HTTP {c}")
c,b,h = set_plan(oid,"team")
# overrides
c,b,h = A.call("PATCH",f"/admin/organizations/{oid}/overrides",{"seat_override":50,"project_override":50,"reason":"bbf"},ST); expect("J6.40","operator override",(c,b,h),200)
c,b,h = call(ot,"POST","/projects",{"name":"overridden-"+RUN,"organization_id":oid}); expect("J6.41","override raises project cap",(c,b,h),201)
c,b,h = A.call("PATCH",f"/admin/organizations/{oid}/overrides",{"seat_override":-1,"reason":"bbf"},ST); expect("J6.42","negative override 422",(c,b,h),[400,422])
c,b,h = A.call("PATCH",f"/admin/organizations/{oid}/overrides",{"seat_override":5},ST); expect("J6.43","override without reason 422",(c,b,h),[400,422])
c,b,h = call(ot,"PATCH",f"/admin/organizations/{oid}/overrides",{"seat_override":5,"reason":"x"}); expect("J6.44","customer token on admin API refused",(c,b,h),[401,403])
# trial expiry: check plan endpoint exposes trial_ends_at
# --- plan flags
c,b,h = call(ot,"PUT",f"/orgs/{slug}/sso",{"protocol":"oidc"}); rec("J6.50","team plan: SSO config refused 402/403 (allow_sso false)",c in(402,403),f"HTTP {c} {json.dumps(b)[:200]}")
c,b,h = call(ot,"POST",f"/orgs/{slug}/scim/token"); rec("J6.51","team plan: SCIM token refused 402/403",c in(402,403),f"HTTP {c} {json.dumps(b)[:200]}")
set_plan(oid,"free")
c,b,h = call(ot,"POST","/account/tokens",{"name":"mcp","scopes":["mcp"],"organization_id":oid}); rec("J6.52","free: mcp token refused (402)",c in(402,403,422),f"HTTP {c} {json.dumps(b)[:200]}")
set_plan(oid,"team")
# --- locked-org / deletion
c,b,h = call(xt,"DELETE",f"/orgs/{slug}"); expect("J5.70","outsider cannot delete org",(c,b,h),[403,404])
c,b,h = call(at,"DELETE",f"/orgs/{slug}"); rec("J5.71","admin cannot delete org (owner only)",c in(403,),f"HTTP {c}")
c,b,h = call(ot,"DELETE",f"/orgs/{slug}"); expect("J5.72","owner requests deletion (grace)",(c,b,h),[200,202])
rec("J5.73","deletion scheduled_for set in future",bool(b.get("deletion_scheduled_for")),json.dumps(b)[:300])
c,b,h = call(ot,"POST","/projects",{"name":"locked-"+RUN,"organization_id":oid}); rec("J5.74","org locked after deletion request: create project 423",c==423,f"HTTP {c} {json.dumps(b)[:150]}")
c,b,h = call(ot,"GET","/projects"); lk=[p for p in b.get("items",b) if p["organization_id"]==oid]
rec("J5.75","projects flagged organization_locked",bool(lk) and all(p.get("organization_locked") for p in lk),str(len(lk)))
c,b,h = call(ot,"PATCH",f"/projects/{lk[0]['id']}",{"version":lk[0]["version"],"name":"locked-rename"}); rec("J5.76","rename project in locked org 423",c==423,f"HTTP {c}")
c,b,h = call(ot,"POST",f"/orgs/{slug}/deletion/cancel"); expect("J5.77","cancel deletion",(c,b,h),[200,204])
c,b,h = call(ot,"POST","/projects",{"name":"unlocked-"+RUN,"organization_id":oid}); expect("J5.78","unlocked after cancel",(c,b,h),201)
c,b,h = call(ot,"DELETE",f"/orgs/{slug}"); did=oid
c,b,h = A.call("PATCH",f"/admin/organizations/{oid}/deletion",{"grace_days":0,"reason":"bbf"},ST); expect("J5.80","operator change grace period to 0",(c,b,h),200)
c,b,h = A.call("POST",f"/admin/organizations/{oid}/deletion/execute",{"reason":"bbf"},ST); expect("J5.81","operator delete-now executes",(c,b,h),[200,204])
c,b,h = call(ot,"GET",f"/orgs/{slug}"); expect("J5.82","org gone for owner",(c,b,h),[403,404])
c,b,h = A.call("GET",f"/admin/organizations/{oid}",None,ST); expect("J5.83","org gone in operator console (or flagged deleted)",(c,b,h),[404,200])
c,b,h = call(ot,"GET","/projects"); rec("J5.84","org's projects really gone",not [p for p in b.get("items",b) if p["organization_id"]==oid],"")
c,b,h = call(ot,"POST","/orgs",{"name":"reuse","slug":slug}); rec("J5.85","slug reusable after deletion (or cleanly refused)",c in(201,409),f"HTTP {c}")
