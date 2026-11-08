import sys, json, time, http.cookiejar, urllib.request, urllib.error
sys.path.insert(0, "/mnt/files/projects/builder-backend/final_test/harness")
import bb

TUNNEL = "https://cinderous-overfamiliar-sanford.ngrok-free.dev"
api = bb.Api(base=TUNNEL)
e = bb.env()
email = e["FINAL_TEST_MEMBER_EMAIL"]
pw = e["FINAL_TEST_PASSWORD"]

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

def post(path, body, extra_headers=None):
    headers = {"Content-Type": "application/json", "ngrok-skip-browser-warning": "1",
               "X-Requested-With": "builder", "Origin": TUNNEL, **(extra_headers or {})}
    req = urllib.request.Request(TUNNEL + path, json.dumps(body).encode() if body is not None else b"{}",
                                  headers, method="POST")
    try:
        with opener.open(req, timeout=15) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as ex:
        return ex.code, ex.read()

# sign up/sign in the member test account first (register if needed)
st, b = post("/account/register", {"email": email, "password": pw, "name": "member"})
if st not in (200, 201):
    st, b = post("/account/login", {"email": email, "password": pw})
print("login/register:", st, str(b)[:150])

refresh_cookie_before = next((c.value for c in cj if "refresh" in c.name.lower() or c.name.startswith("bb")), None)
print("cookies present:", [c.name for c in cj])

# first refresh: should succeed, rotate the cookie
st1, b1 = post("/account/refresh", {})
print("refresh #1 (fresh):", st1, str(b1)[:150])
cookie_after_1 = {c.name: c.value for c in cj}

# wait past the 10s reuse-grace window, then REPLAY using a cookie jar that still has the OLD (already-used) cookie
# simulate by making a second opener seeded with the ORIGINAL cookie captured before refresh #1
time.sleep(11)

# reconstruct an opener carrying the pre-refresh cookie value (the one that's now already consumed)
cj_old = http.cookiejar.CookieJar()
# we need the cookie as it was right after login, before refresh #1 rotated it -- capture via a parallel login
cj2 = http.cookiejar.CookieJar()
opener2 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj2))
def post2(path, body):
    headers = {"Content-Type": "application/json", "ngrok-skip-browser-warning": "1",
               "X-Requested-With": "builder", "Origin": TUNNEL}
    req = urllib.request.Request(TUNNEL + path, json.dumps(body).encode(), headers, method="POST")
    try:
        with opener2.open(req, timeout=15) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as ex:
        return ex.code, ex.read()

st_login2, _ = post2("/account/login", {"email": email, "password": pw})
print("fresh login #2 for a clean reuse test:", st_login2)

# refresh ONCE (consumes refresh token v1 -> issues v2), capturing both cookie jars' states along the way
import copy
cj_snapshot_v1 = {c.name: c.value for c in cj2}  # the ORIGINAL refresh cookie (v1), before any refresh call
st_r1, _ = post2("/account/refresh", {})
cj_snapshot_v2 = {c.name: c.value for c in cj2}  # the NEW refresh cookie (v2), after rotation
print("refresh using v1 ->", st_r1, "cookie rotated:", cj_snapshot_v1 != cj_snapshot_v2)

# Now REPLAY the OLD (v1) cookie directly, by hand, well past the reuse-grace window
time.sleep(11)
old_cookie_header = "; ".join(f"{k}={v}" for k, v in cj_snapshot_v1.items())
req = urllib.request.Request(TUNNEL + "/account/refresh", b"{}", {
    "Content-Type": "application/json", "ngrok-skip-browser-warning": "1",
    "X-Requested-With": "builder", "Origin": TUNNEL, "Cookie": old_cookie_header,
}, method="POST")
try:
    with urllib.request.urlopen(req, timeout=15) as r:
        st_replay = r.status; b_replay = r.read()
except urllib.error.HTTPError as ex:
    st_replay = ex.code; b_replay = ex.read()
print("REPLAY old (v1) refresh token after rotation + grace window ->", st_replay, str(b_replay)[:150])

# Now check whether the family was revoked: try the LEGITIMATE current (v2) cookie -- should it still work, or did reuse kill the whole family?
new_cookie_header = "; ".join(f"{k}={v}" for k, v in cj_snapshot_v2.items())
req2 = urllib.request.Request(TUNNEL + "/account/refresh", b"{}", {
    "Content-Type": "application/json", "ngrok-skip-browser-warning": "1",
    "X-Requested-With": "builder", "Origin": TUNNEL, "Cookie": new_cookie_header,
}, method="POST")
try:
    with urllib.request.urlopen(req2, timeout=15) as r:
        st_v2 = r.status; b_v2 = r.read()
except urllib.error.HTTPError as ex:
    st_v2 = ex.code; b_v2 = ex.read()
print("using the CURRENT (v2) token after the v1 replay was detected ->", st_v2, str(b_v2)[:150])

result = {
    "refresh_v1_rotated_to_v2": st_r1,
    "replay_old_v1_after_grace_window": {"status": st_replay, "body": str(b_replay)[:200]},
    "use_current_v2_after_v1_replay_detected": {"status": st_v2, "body": str(b_v2)[:200]},
}
with open("/mnt/files/projects/builder-backend/final_test/security/evidence/refresh_rotation_result.json", "w") as f:
    json.dump(result, f, indent=2, default=str)
print(json.dumps(result, indent=2, default=str))
