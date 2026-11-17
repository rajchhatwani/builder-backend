from lib import *
em=user('lock')[0]
# lockout / rate limit
em2=em
codes=[]
for i in range(15):
    c,b,h = A.call("POST","/account/login",{"email":em2,"password":"wrongwrongwrong%d"%i}); codes.append(c)
rec("J1.30","repeated bad logins eventually 429/423 with clear message",any(x in (429,423) for x in codes),str(codes))
c,b,h = A.call("POST","/account/login",{"email":em2,"password":PW})
rec("J1.31","correct password during lockout is refused (429/423) or accepted — record",True,f"HTTP {c} {json.dumps(b)[:200]} retry-after={h.get('Retry-After')}")
c,b,h = A.call("POST","/account/login",{"email":em2,"password":"wrongwrongwrong"})
rec("J1.32","lockout response has Retry-After or human message", c in(429,423) and (h.get("Retry-After") or b.get("message")), f"{c} {b} {h.get('Retry-After')}")
# register rate limit
codes=[]
for i in range(25):
    c,_,_ = A.call("POST","/account/register",{"email":f"bbf-rl{i}-{RUN}@dumbpotato.com","password":PW,"name":"r"}); codes.append(c)
rec("J1.33","register burst eventually 429",429 in codes,str(codes))

