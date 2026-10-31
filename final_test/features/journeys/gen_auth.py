# exec()'d: generated auth project journey
import re as _re
s, oa = g("GET", "/openapi.json"); P = oa["paths"]
rec(J+".auth.routes", "auth routes present", any(p.startswith("/auth") for p in P), ", ".join(sorted(p for p in P if p.startswith("/auth"))))
em = f"u{RUN}@example.com"; pw = "Sup3r-secret-pw!"
def mail_for(to, timeout=20):
    return bb.wait_mail(to=to, subject="", timeout=timeout)
def tok_from(m):
    mm = _re.search(r"(?:token|code)=(\S+)", m["body"]) or _re.search(r"\b(\d{6})\b", m["body"])
    return mm.group(1) if mm else None
s, r = g("POST", "/auth/register", {"email": em, "password": pw, "full_name": "T U", "age": 30}); rec(J+".auth.register", "register 201", s in (200, 201), f"{s} {json.dumps(r)[:200]}")
s, r = g("POST", "/auth/register", {"email": em, "password": pw, "full_name": "T U", "age": 30}); rec(J+".auth.dup", "duplicate register 409", s == 409, f"{s}")
s, r = g("POST", "/auth/register", {"email": "b"+em, "password": pw, "full_name": "T", "age": 5}); rec(J+".auth.cf", "custom-field validation 422", s == 422, f"{s}")
s, r = g("POST", "/auth/register", {"email": "c"+em, "password": "x", "full_name": "Tt"}); rec(J+".auth.weak", "weak password 422", s == 422, f"{s}")
s, r = g("POST", "/auth/register", {"email": "d"+em, "password": pw, "full_name": "Tt", "plan": "gold"}); rec(J+".auth.enum", "enum custom field rejects unknown value", s == 422, f"{s}")
s, r = g("POST", "/auth/login", {"email": em, "password": pw}); rec(J+".auth.unverified", "login before verification refused", s in (401, 403), f"{s} {json.dumps(r)[:150]}")
s, r = g("POST", "/auth/login", {"email": em, "password": "wrong"}); rec(J+".auth.badpw", "wrong password 401", s == 401, f"{s}")
m = mail_for(em); rec(J+".auth.mail", "verification mail delivered", bool(m), "")
tk = tok_from(m) if m else None
s, r = g("POST", "/auth/email/verify", {"token": "nope"}); rec(J+".auth.verify_bad", "bad verification token refused", s in (400, 401, 404, 410, 422), f"{s}")
s, r = g("POST", "/auth/email/verify", {"token": tk}); rec(J+".auth.verify", "verify e-mail", s == 200, f"{s} {json.dumps(r)[:150]} toklen={len(tk or '')} links={len(m['links'])}")
s, r = g("POST", "/auth/email/verify", {"token": tk}); rec(J+".auth.verify_twice", "verification token single-use", s in (400, 401, 404, 410, 422), f"{s}")
s, r = g("POST", "/auth/login", {"email": em, "password": pw}); rec(J+".auth.login", "login after verify", s == 200 and "access_token" in r, f"{s}")
at, rt = r.get("access_token"), r.get("refresh_token"); H = {"Authorization": "Bearer " + (at or "x")}
s, r = g("GET", "/auth/me", None, H); rec(J+".auth.me", "/auth/me", s == 200 and r.get("email") == em, f"{s} {json.dumps(r)[:200]}")
rec(J+".auth.me_nosecret", "/auth/me exposes no password hash", "password" not in json.dumps(r).lower(), "")
rec(J+".auth.role_default", "default role customer", "customer" in json.dumps(r), json.dumps(r)[:200])
s, r = g("GET", "/auth/me"); rec(J+".auth.me_anon", "/auth/me anonymous 401", s == 401, f"{s}")
s, r = g("GET", "/auth/me", None, {"Authorization": "Bearer junk"}); rec(J+".auth.me_junk", "junk token 401", s == 401, f"{s}")
s, r = g("POST", "/auth/refresh", {"refresh_token": rt}); rec(J+".auth.refresh", "refresh", s == 200, f"{s}"); rt2 = r.get("refresh_token")
s, r = g("POST", "/auth/refresh", {"refresh_token": rt}); rec(J+".auth.refresh_reuse", "old refresh token reuse refused", s == 401, f"{s}")
s, r = g("POST", "/auth/refresh", {"refresh_token": rt2}); rec(J+".auth.refresh_family", "after reuse detection the family is revoked (or not): record", True, f"{s}")
s, r = g("POST", "/auth/login", {"email": em, "password": pw}); rec(J+".auth.relogin", "login again after refresh reuse", s == 200, f"{s} {json.dumps(r)[:200]}"); at, rt = r.get("access_token", ""), r.get("refresh_token", ""); H = {"Authorization": "Bearer " + at}
s, r = g("POST", "/auth/change-password", {"current_password": pw, "new_password": pw + "2"}, H); rec(J+".auth.chpw", "change password", s in (200, 204), f"{s} {json.dumps(r)[:150]}")
s, r = g("POST", "/auth/login", {"email": em, "password": pw}); rec(J+".auth.chpw_old", "old password rejected", s == 401, f"{s}")
s, r = g("POST", "/auth/magic-link/request", {"email": em}); rec(J+".auth.magic_req", "magic link request 202", s == 202, f"{s}")
s2, r2 = g("POST", "/auth/magic-link/request", {"email": "nobody"+em}); rec(J+".auth.magic_enum", "magic-link request does not reveal unknown e-mail", s2 == s, f"{s2}")
s, r = g("POST", "/auth/password-reset/request", {"email": em}); rec(J+".auth.reset_req", "password reset request", s in (200, 202), f"{s}")
ms = None
for _ in range(10):
    m2 = bb.wait_mail(to=em, subject="reset", timeout=5)
    if m2: ms = m2; break
if ms:
    tk2 = tok_from(ms)
    s, r = g("POST", "/auth/password-reset/confirm", {"token": tk2, "new_password": "N3w-secret-pw!!"}); rec(J+".auth.reset", "password reset with mailed token", s in (200, 204), f"{s} {json.dumps(r)[:120]}")
    s, r = g("POST", "/auth/password-reset/confirm", {"token": tk2, "new_password": "N3w-secret-pw!!x"}); rec(J+".auth.reset_twice", "reset token single-use", s in (400, 401, 404, 410, 422), f"{s}")
    s, r = g("POST", "/auth/login", {"email": em, "password": "N3w-secret-pw!!"}); rec(J+".auth.reset_login", "login with reset password", s == 200, f"{s}")
else:
    rec(J+".auth.reset", "reset mail delivered", False, "no reset mail")
for i in range(40):
    s, r = g("POST", "/auth/login", {"email": em, "password": "bad"})
    if s == 429: break
rec(J+".auth.ratelimit", "generated login rate limit kicks in (429) within 40 bad attempts", s == 429, f"last {s} after {i+1}")
