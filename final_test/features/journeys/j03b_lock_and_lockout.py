from lib import *
import concurrent.futures as cf
for _ in range(40):
    try: em, t = user("lkr"); break
    except AssertionError: time.sleep(15)
c, p, _ = call(t, "POST", "/projects", {"name": "lock-" + RUN}); pid = p["id"]
res = []
for rnd in range(3):
    v = call(t, "GET", f"/projects/{pid}")[1]["version"]
    def rn(i): return call(t, "PATCH", f"/projects/{pid}", {"version": v, "name": f"par{rnd}-{i}-{RUN}"})[0]
    with cf.ThreadPoolExecutor(8) as ex: codes = list(ex.map(rn, range(8)))
    res.append(codes.count(200))
rec("J3.lock_race2", "8 parallel PATCH with one stale version: exactly one 200 per round", res == [1, 1, 1], f"winners per round {res}")
# lockout visible to the user?
em2, _ = user("lk3")
for i in range(5): A.call("POST", "/account/login", {"email": em2, "password": "wrongwrong%d" % i})
c, b, h = A.call("POST", "/account/login", {"email": em2, "password": PW})
rec("J1.30b", "5 bad passwords lock the account silently: correct password then gets generic 401 with no lock message", c == 401 and "lock" not in json.dumps(b).lower(), f"{c} {b}")
