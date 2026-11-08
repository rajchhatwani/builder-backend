from lib import *
ST = A.staff("admin"); SUP = None
try: SUP = A.staff("support")
except Exception as e: rec("J11.00", "support staff login", False, str(e)[:100])
oe, ot = user("fown"); me, mt = user("fmem")
c, org, _ = call(ot, "POST", "/orgs", {"name": "PhaseF " + RUN}); slug, oid = org["slug"], org["id"]
A.call("PATCH", f"/admin/organizations/{oid}/plan", {"plan_id": "team", "reason": "bbf"}, ST)
c, b, _ = call(ot, "POST", f"/orgs/{slug}/invitations", {"email": me, "role": "member"}); call(mt, "POST", "/orgs/invitations/accept", {"token": b["token"]})
mid = [m for m in call(ot, "GET", f"/orgs/{slug}/members")[1]["items"] if m["email"] == me][0]["user_id"]
c, p, _ = call(ot, "POST", "/projects", {"name": "imp-" + RUN, "organization_id": oid}); pid = p["id"]
# --- operator console
for path in ["/admin/me", "/admin/users", "/admin/organizations", "/admin/projects", "/admin/audit", "/admin/stats", "/admin/settings", "/admin/plans", "/admin/subscriptions", "/admin/insights"]:
    c, b, _ = A.call("GET", path, None, ST); rec("J11.10", f"admin GET {path}", c == 200, f"{c}")
    if SUP:
        c2, b2, _ = A.call("GET", path, None, SUP); rec("J11.11", f"support GET {path} allowed read-only", c2 in (200, 403), f"{c2}")
    c3, _, _ = A.call("GET", path, None, ot); rec("J11.12", f"customer token on {path} refused", c3 in (401, 403), f"{c3}")
    c4, _, _ = A.call("GET", path); rec("J11.13", f"anonymous {path} 401", c4 == 401, f"{c4}")
if SUP:
    c, b, _ = A.call("PATCH", f"/admin/organizations/{oid}/plan", {"plan_id": "business", "reason": "x"}, SUP); rec("J11.20", "support cannot change plan", c == 403, f"{c}")
    c, b, _ = A.call("POST", f"/admin/users/{mid}/reset-password", {"reason": "x"}, SUP); rec("J11.21", "support cannot reset password", c == 403, f"{c}")
    c, b, _ = A.call("POST", f"/admin/organizations/{oid}/members/{mid}/impersonate", {"reason": "support test"}, SUP); rec("J11.22", "support impersonation (record)", c in (200, 201, 403), f"{c}")
    c, b, _ = A.call("PUT", "/admin/plans/team", {}, SUP); rec("J11.23", "support cannot edit plans", c in (403, 422), f"{c}")
c, b, _ = A.call("GET", "/admin/users?limit=5000&offset=-1", None, ST); rec("J11.30", "admin list absurd paging not 500", c < 500, f"{c}")
c, b, _ = A.call("GET", "/admin/users?q=" + "%27%3B--", None, ST); rec("J11.31", "admin search SQL chars not 500", c < 500, f"{c}")
c, b, _ = A.call("GET", "/admin/audit?action=" + "x" * 500, None, ST); rec("J11.32", "audit filter long value not 500", c < 500, f"{c}")
c, pl, _ = A.call("GET", "/admin/plans", None, ST); team = [x for x in (pl if isinstance(pl, list) else pl["items"]) if x["id"] == "team"][0]
for k, v in [("max_seats", -1), ("max_projects", "x"), ("monthly_price_usd", -5)]:
    c, b, _ = A.call("PUT", "/admin/plans/team", {**team, k: v, "reason": "bbf"}, ST); rec("J11.40", f"plan edit invalid {k}={v} -> 422", c in (400, 422), f"{c}")
# user admin
c, b, _ = A.call("POST", f"/admin/users/{mid}/reset-password", {"reason": "bbf"}, ST); rec("J11.50", "operator reset password returns a temporary password once", c == 200, f"{c} keys={list(b)[:4]}")
if c == 200:
    tmp = b.get("temporary_password") or b.get("password"); c2, b2, _ = A.call("POST", "/account/login", {"email": me, "password": tmp}); rec("J11.51", "temp password logs in and forces change", c2 == 200 and b2.get("user", {}).get("must_change_password") is True, f"{c2}")
    tk = b2.get("access_token"); c3, b3, _ = call(tk, "GET", "/projects"); rec("J11.52", "forced-change session blocked from other APIs (403/428)", c3 in (403, 428, 423), f"{c3}")
    c4, _, _ = call(tk, "POST", "/account/password", {"current_password": tmp, "new_password": PW}); rec("J11.53", "forced password change works", c4 in (200, 204), f"{c4}")
c, b, _ = A.call("POST", f"/admin/users/{mid}/revoke-sessions", {"reason": "bbf"}, ST); rec("J11.54", "revoke sessions", c in (200, 204), f"{c}")
# --- impersonation
c, b, _ = call(ot, "PATCH", f"/orgs/{slug}/policies", {"allow_impersonation": False}); rec("J13.01", "owner disables impersonation consent", c == 200, f"{c}")
c, b, _ = A.call("POST", f"/admin/organizations/{oid}/members/{mid}/impersonate", {"reason": "consent off test"}, ST); rec("J13.02", "impersonation refused when org withdrew consent", c in (403, 409), f"{c} {json.dumps(b)[:120]}")
call(ot, "PATCH", f"/orgs/{slug}/policies", {"allow_impersonation": True})
c, b, _ = A.call("POST", f"/admin/organizations/{oid}/members/{mid}/impersonate", {"reason": "x"}, ST); rec("J13.03", "short reason refused", c == 422, f"{c}")
c, b, _ = A.call("POST", f"/admin/organizations/{oid}/members/{mid}/impersonate", {"reason": "bbf feature test"}, ST); rec("J13.04", "operator starts viewing session", c in (200, 201), f"{c} keys={list(b)[:5]}")
it = b.get("access_token"); sid = b.get("session_id")
if it:
    c, b, _ = call(it, "GET", "/account/impersonation"); rec("J13.05", "banner state endpoint", c == 200 and b.get("user_email") == me, f"{c}")
    c, b, _ = call(it, "GET", "/projects"); rec("J13.06", "viewing token reads projects", c == 200, f"{c}")
    c, b, _ = call(it, "POST", "/projects", {"name": "wr-" + RUN, "organization_id": oid}); rec("J13.07", "viewing is read-only by default (write blocked)", c in (403, 423), f"{c} {json.dumps(b)[:100]}")
    for m_, pth, body in [("POST", "/account/tokens", {"name": "t", "scopes": ["read"]}), ("POST", "/account/password", {"current_password": "a", "new_password": "b"}), ("POST", "/account/mfa/totp/setup", {"password": "x"}), ("DELETE", f"/orgs/{slug}/members/{mid}", None)]:
        c, b, _ = call(it, m_, pth, body); rec("J13.08", f"viewing token cannot {m_} {pth}", c in (401, 403, 423), f"{c}")
    c, b, _ = call(it, "GET", "/mcp/"); c2, b2, _ = call(it, "GET", f"/orgs/{slug}/export"); rec("J13.09", "viewing token cannot export org data", c2 in (401, 403), f"{c2}")
    c, b, _ = call(it, "POST", "/account/impersonation/writes", {"enabled": True}); rec("J13.10", "member consent to writes (record)", c in (200, 403), f"{c}")
    c, b, _ = call(ot, "GET", f"/orgs/{slug}/audit?limit=20"); rec("J13.11", "owner sees impersonation in audit", any("imperson" in i["action"] for i in b["items"]), ",".join(sorted({i['action'] for i in b['items']}))[:150])
    c, b, _ = A.call("GET", "/admin/impersonation/sessions", None, ST); rec("J13.12", "operator sessions list", c == 200, f"{c}")
    c, b, _ = A.call("POST", f"/admin/impersonation/sessions/{sid}/end", {}, ST); rec("J13.13", "operator ends session", c in (200, 204), f"{c}")
    c, b, _ = call(it, "GET", "/projects"); rec("J13.14", "ended token refused", c == 401, f"{c}")
c, b, _ = A.call("GET", "/admin/impersonation/digest", None, ST); rec("J13.15", "digest endpoint", c == 200, f"{c}")
# --- per-org export
c, b, _ = call(ot, "GET", f"/orgs/{slug}/export"); rec("J13.20", "owner export", c == 200, f"{c} {len(json.dumps(b))}B")
s = json.dumps(b); rec("J13.21", "export has no password hashes / tokens / secrets", not any(k in s.lower() for k in ("password_hash", "token_hash", "\"secret\"", "bb_inv_", "bbk_")), "")
c, b, _ = call(mt, "GET", f"/orgs/{slug}/export"); rec("J13.22", "member cannot export", c == 403, f"{c}")
ox, ot2 = user("fout"); c, b, _ = call(ot2, "GET", f"/orgs/{slug}/export"); rec("J13.23", "outsider cannot export", c in (403, 404), f"{c}")
# --- org policies / MFA
c, b, _ = call(ot, "PATCH", f"/orgs/{slug}/policies", {"require_mfa": True}); rec("J10.01", "require_mfa refused until owner has MFA (enable_mfa_first)", c == 409, f"{c} {b.get('code')}")
c, b, _ = call(ot, "POST", "/account/mfa/totp/setup", {"password": PW}); sec = b["secret"]; call(ot, "POST", "/account/mfa/totp/enable", {"code": bb.totp(sec)})
c, b, _ = A.call("POST", "/account/login", {"email": oe, "password": PW}); mt_ = b["mfa_token"]; time.sleep(30 - time.time() % 30 + 1)
c, b, _ = A.call("POST", "/account/login/mfa", {"mfa_token": mt_, "code": bb.totp(sec)}); ot = b["access_token"]
c, b, _ = call(ot, "PATCH", f"/orgs/{slug}/policies", {"require_mfa": True}); rec("J10.02", "owner with MFA enables require_mfa", c == 200, f"{c} {json.dumps(b)[:150]}")
c, b, _ = A.call("POST", "/account/login", {"email": me, "password": PW}); mtk = b.get("access_token")
c, b, _ = call(mtk, "GET", f"/orgs/{slug}"); rec("J10.03", "member without MFA is blocked from the org (prompt, 403 mfa_required)", c in (403, 423) and "mfa" in json.dumps(b).lower(), f"{c} {json.dumps(b)[:150]}")
c, b, _ = call(mtk, "GET", "/projects"); rec("J10.04", "member without MFA: org project list excludes/blocks org projects", c in (200, 403) and (c == 403 or pid not in json.dumps(b)), f"{c}")
c, b, _ = call(mtk, "GET", f"/projects/{pid}"); rec("J10.05", "member without MFA cannot open org project directly", c in (403, 404), f"{c}")
c, b, _ = call(mtk, "POST", "/account/tokens", {"name": "bypass", "scopes": ["read"], "project_id": pid}); tkn = b.get("token")
if tkn: c, b, _ = A.call("GET", f"/projects/{pid}", None, tkn); rec("J10.06", "API token cannot bypass require_mfa", c in (403, 404), f"{c}")
c, b, _ = call(ot, "PATCH", f"/orgs/{slug}/policies", {"session_ttl_hours": 1}); rec("J10.07", "set session TTL 1h", c == 200, f"{c}")
c, b, _ = call(ot, "PATCH", f"/orgs/{slug}/policies", {"require_mfa": False, "session_ttl_hours": None}); rec("J10.08", "disable policies", c == 200, f"{c}")
c, b, _ = call(ot, "GET", f"/orgs/{slug}/audit?limit=5&offset=5"); rec("J10.09", "audit pagination offset", c == 200, f"{c}")
