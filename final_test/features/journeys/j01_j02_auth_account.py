from lib import *
import concurrent.futures as cf

# --- J1 sign-up / login ---
em, tok = user("a")
expect("J1.01","register ok",(201,{}, {}),201)
c,b,h = A.call("POST","/account/register",{"email":em,"password":PW,"name":"dup"})
expect("J1.02","duplicate email register refused (no enumeration detail leak)",(c,b,h),[409,400,422])
rec("J1.02b","dup register message does not confirm account existence", "already" not in json.dumps(b).lower() , json.dumps(b))
c,b,h = A.call("POST","/account/register",{"email":em.upper(),"password":PW,"name":"x"})
expect("J1.03","e-mail case variant of existing account refused",(c,b,h),[409,400,422])
for pw,lbl in [("short","short pw"),("a"*300,"300-char pw"),("",'empty pw'),("password","common pw"),("12345678","numeric pw")]:
    c,b,h = A.call("POST","/account/register",{"email":f"bbf-pw{abs(hash(pw))%999}-{RUN}@dumbpotato.com","password":pw,"name":"x"})
    expect("J1.04","weak/oversized password refused: "+lbl,(c,b,h),[400,422])
for e in ["notanemail","a@b","@x.com","x@"+"a"*300+".com","","a b@c.com","ünï@dumbpotato.com","ü@dumbpotato.com"]:
    c,b,h = A.call("POST","/account/register",{"email":e,"password":PW,"name":"x"})
    rec("J1.05","bad/odd email handled w/o 5xx: %r"%e[:30], c<500, f"HTTP {c}")
c,b,h = A.call("POST","/account/register",{"email":f"bbf-<script>-{RUN}@dumbpotato.com","password":PW,"name":"<img src=x onerror=alert(1)>"})
rec("J1.06","HTML in name accepted or cleanly refused",c in (201,422,400), f"HTTP {c}")
c,b,h = A.call("POST","/account/register",{"email":f"bbf-nul-{RUN}@dumbpotato.com","password":PW,"name":"a\u0000b"})
rec("J1.07","NUL char in name -> 4xx not 500",c<500,f"HTTP {c}")
# login
c,b,h = A.call("POST","/account/login",{"email":em,"password":PW}); expect("J1.10","login ok",(c,b,h),200)
c,b,h = A.call("POST","/account/login",{"email":em.upper(),"password":PW}); expect("J1.11","login e-mail case-insensitive",(c,b,h),200)
c,b,h = A.call("POST","/account/login",{"email":"  "+em+" ","password":PW}); rec("J1.12","login with surrounding whitespace -> 200 or clean 4xx",c in(200,401,422),f"HTTP {c}")
c,b,h = A.call("POST","/account/login",{"email":em,"password":"wrongwrongwrong"}); expect("J1.13","wrong password 401",(c,b,h),401)
c2,b2,_ = A.call("POST","/account/login",{"email":"nobody-%s@dumbpotato.com"%RUN,"password":"wrongwrongwrong"})
rec("J1.14","unknown user and wrong password give identical error body",(c,b.get("code"),b.get("message"))==(c2,b2.get("code"),b2.get("message")),f"{b} vs {b2}")
c,b,h = A.call("POST","/account/login/discover",{"email":em}); rec("J1.15","discover for plain account: no SSO",c==200 and not b.get("sso"),f"{c} {b}")
c,b,h = A.call("POST","/account/login/discover",{"email":"x@dumbpotato.com"}); rec("J1.16","discover for SSO-domain email returns sso redirect",c==200 and (b.get("sso") or b.get("method") or "slug" in json.dumps(b) or "bb-sso" in json.dumps(b)),f"{c} {b}")
# refresh / logout via cookie
import urllib.request, urllib.error
CK={}
def jc(m,p,body=None,tk=None):
    hd={"Content-Type":"application/json","X-Requested-With":"builder"}
    if tk: hd["Authorization"]="Bearer "+tk
    if CK: hd["Cookie"]="; ".join(f"{k}={v}" for k,v in CK.items())
    r=urllib.request.Request(A.base+p,json.dumps(body).encode() if body is not None else None,hd,method=m)
    try:
        x=urllib.request.urlopen(r); st,raw,hh=x.status,x.read(),x.headers
    except urllib.error.HTTPError as e:
        st,raw,hh=e.code,e.read(),e.headers
    for sc in hh.get_all("Set-Cookie") or []:
        k,_,v=sc.split(";")[0].partition("=")
        if "Max-Age=0" in sc or v=="" : CK.pop(k,None)
        else: CK[k]=v
    try: return st,json.loads(raw or b"{}"),dict(hh)
    except Exception: return st,{},dict(hh)
c,b,h = jc("POST","/account/login",{"email":em,"password":PW}); at=b.get("access_token")
sc=h.get("set-cookie","")+"|"+str(list(CK))
rec("J1.20","refresh cookie HttpOnly+SameSite+Path",("httponly" in sc.lower() and "samesite" in sc.lower() and "secure" in sc.lower()),redact(sc[:160]))
c,b,h = jc("POST","/account/refresh"); expect("J1.21","refresh returns new access token",(c,b,h),200); at2=b.get("access_token")
c,b,h = jc("POST","/account/refresh"); rec("J1.22","second refresh with rotated cookie works",c==200,f"{c}")
# reuse of old refresh cookie (rotation reuse detection)
old = list(CK.values())[0]
c,b,h = jc("GET","/account/me",None,at2); expect("J1.23","/me with refreshed token",(c,b,h),200)
c,b,h = jc("POST","/account/logout"); expect("J1.24","logout",(c,b,h),[200,204])
c,b,h = jc("POST","/account/refresh"); rec("J1.25","refresh after logout -> 401",c==401,f"{c}")
c,b,h = A.call("GET","/account/me",None,"garbage"); expect("J1.26","garbage bearer 401",(c,b,h),401)
c,b,h = A.call("GET","/account/me"); expect("J1.27","anonymous /me 401",(c,b,h),401)
# --- password change ---
em3,t3 = user("pw")
c,b,h = call(t3,"POST","/account/password",{"current_password":"nope-nope-nope","new_password":PW+"x"}); expect("J1.40","pw change wrong current 4xx",(c,b,h),[400,401,403,422])
c,b,h = call(t3,"POST","/account/password",{"current_password":PW,"new_password":"short"}); expect("J1.41","pw change weak new refused",(c,b,h),[400,422])
c,b,h = call(t3,"POST","/account/password",{"current_password":PW,"new_password":PW}); rec("J1.42","pw change to same password refused or noted",c in(200,204,400,422),f"{c} {b}")
NEW = PW+"Zz9!"
c,b,h = call(t3,"POST","/account/password",{"current_password":PW,"new_password":NEW}); expect("J1.43","pw change ok",(c,b,h),[200,204])
c,b,h = A.call("POST","/account/login",{"email":em3,"password":PW}); expect("J1.44","old pw rejected",(c,b,h),401)
c,b,h = A.call("POST","/account/login",{"email":em3,"password":NEW}); expect("J1.45","new pw works",(c,b,h),200)
c,b,h = call(t3,"GET","/account/me"); rec("J1.46","old access token after pw change: revoked or still valid (record)",True,f"HTTP {c}")
# logout-all
em4,t4 = user("la"); c,b,h = A.call("POST","/account/login",{"email":em4,"password":PW}); t4b=b["access_token"]
c,b,h = call(t4,"POST","/account/logout-all"); expect("J1.47","logout-all",(c,b,h),[200,204])
c,b,h = call(t4b,"GET","/account/me"); rec("J1.48","other session token rejected after logout-all",c==401,f"HTTP {c}")

# --- J2 API tokens ---
em5,t5 = user("tok")
c,b,h = call(t5,"GET","/account/me"); me=b; 
c,b,h = call(t5,"GET","/orgs"); org=(b["items"][0] if b.get("items") else None)
rec("J2.00","personal org exists after signup",bool(org) and org.get("kind")=="personal",json.dumps(b)[:300])
c,b,h = call(t5,"POST","/account/tokens",{"name":"bbf-read","scopes":["read"]}); print("token create shape:",c,list(b.keys()) if isinstance(b,dict) else b)
expect("J2.01","create token",(c,b,h),201)
tid=b.get("id"); raw=b.get("token") or b.get("secret")
rec("J2.02","raw token shown once and not in list", bool(raw) and raw not in json.dumps(call(t5,"GET","/account/tokens")[1]),"")
c,b,h = A.call("GET","/account/me",None,raw); rec("J2.03","API token authenticates /account/me (or is refused for account API)",c in(200,401,403),f"HTTP {c}")
c,b,h = A.call("GET","/projects",None,raw); expect("J2.04","read-scoped token can list projects",(c,b,h),200)
c,b,h = A.call("POST","/projects",{"name":"tokwrite-"+RUN},raw); expect("J2.05","read-scoped token cannot create project",(c,b,h),[401,403])
c,b,h = call(t5,"POST","/account/tokens",{"name":"bbf-write","scopes":["write"]}); w=b.get("token") 
c2,b2,h2 = A.call("POST","/projects",{"name":"tokwrite-"+RUN},w); expect("J2.06","write token creates project",(c2,b2,h2),[200,201])
c,b,h = call(t5,"POST","/account/tokens",{"name":"x","scopes":["bogus"]}); expect("J2.07","unknown scope refused",(c,b,h),[400,422])
c,b,h = call(t5,"POST","/account/tokens",{"name":"","scopes":["read"]}); expect("J2.08","empty token name refused",(c,b,h),[400,422])
c,b,h = call(t5,"POST","/account/tokens",{"name":"n"*500,"scopes":["read"]}); expect("J2.09","500-char token name refused",(c,b,h),[400,422])
c,b,h = call(t5,"DELETE",f"/account/tokens/{tid}"); expect("J2.10","revoke token",(c,b,h),[200,204])
c,b,h = A.call("GET","/projects",None,raw); expect("J2.11","revoked token refused",(c,b,h),401)
c,b,h = call(t5,"DELETE",f"/account/tokens/{uuid.uuid4()}"); expect("J2.12","revoke unknown token 404",(c,b,h),404)
# quota
codes=[]
for i in range(60):
    c,b,h = call(t5,"POST","/account/tokens",{"name":f"q{i}","scopes":["read"]}); codes.append(c)
    if c!=201: last=(c,b); break
rec("J2.13","API token quota gives 402 at n+1 with resource name",codes[-1]==402 and "token" in json.dumps(last[1]).lower(),f"{codes.count(201)} created; {last}")
# --- TOTP ---
em6,t6 = user("mfa")
c,b,h = call(t6,"GET","/account/mfa"); rec("J2.20","mfa status off",c==200 and not b.get("enabled",b.get("totp_enabled",False)),f"{b}")
c,b,h = call(t6,"POST","/account/mfa/totp/setup",{"password":PW}); expect("J2.21","totp setup",(c,b,h),200)
sec=b.get("secret") or b.get("totp_secret"); print("setup keys",list(b.keys()))
c,b,h = call(t6,"POST","/account/mfa/totp/enable",{"code":"000000"}); expect("J2.22","enable with wrong code refused",(c,b,h),[400,401,422])
code=bb.totp(sec)
c,b,h = call(t6,"POST","/account/mfa/totp/enable",{"code":code}); expect("J2.23","enable with right code",(c,b,h),200)
rc=b.get("recovery_codes") or []
rec("J2.24","recovery codes returned (count>=8)",len(rc)>=8,f"n={len(rc)}")
c,b,h = A.call("POST","/account/login",{"email":em6,"password":PW}); rec("J2.25","login now requires mfa",c==200 and b.get("mfa_required"),f"{c} {list(b)}")
mt=b.get("mfa_token")
c,b,h = A.call("POST","/account/login/mfa",{"mfa_token":mt,"code":"123456"}); expect("J2.26","wrong mfa code 401",(c,b,h),401)
time.sleep(30-time.time()%30+1)
c,b,h = A.call("POST","/account/login/mfa",{"mfa_token":mt,"code":bb.totp(sec)}); expect("J2.27","right mfa code logs in",(c,b,h),200); t6=b.get("access_token")
c,b,h = A.call("POST","/account/login",{"email":em6,"password":PW}); mt=b["mfa_token"]
c,b,h = A.call("POST","/account/login/mfa",{"mfa_token":mt,"code":rc[0]}); expect("J2.28","recovery code logs in",(c,b,h),200)
c,b,h = A.call("POST","/account/login",{"email":em6,"password":PW}); mt=b["mfa_token"]
c,b,h = A.call("POST","/account/login/mfa",{"mfa_token":mt,"code":rc[0]}); expect("J2.29","recovery code single-use",(c,b,h),401)
c,b,h = call(t6,"POST","/account/mfa/totp/disable",{"code":"000000"}); expect("J2.30","disable with wrong code refused",(c,b,h),[400,401,403,422])
time.sleep(30-time.time()%30+1)
c,b,h = call(t6,"POST","/account/mfa/totp/disable",{"code":bb.totp(sec),"password":PW}); expect("J2.31","disable mfa",(c,b,h),[200,204])
c,b,h = call(t6,"POST","/account/mfa/recovery-codes",{"code":"000000"}); rec("J2.32","regen recovery codes without valid code refused",c in(400,401,403,422),f"{c}")
