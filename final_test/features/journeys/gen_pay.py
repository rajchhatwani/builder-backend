# exec()'d: payments + storage generated project (real Stripe test key)
import re as _re, hmac, hashlib
em = f"u{RUN}@example.com"; pw = "Sup3r-secret-pw!"
def mail_for(to, timeout=30): return bb.wait_mail(to=to, subject="", timeout=timeout)
def tok_from(m):
    mm = _re.search(r"(?:token|code)=(\S+)", m["body"]) or _re.search(r"\b(\d{6})\b", m["body"]); return mm.group(1) if mm else None
s, r = g("POST", "/auth/register", {"email": em, "password": pw}); rec(J+".pay.register", "customer registers", s in (200, 201), f"{s} {json.dumps(r)[:200]}")
m = mail_for(em); tk = tok_from(m) if m else None
s, r = g("POST", "/auth/email/verify", {"token": tk}); rec(J+".pay.verify", "customer verifies e-mail", s == 200, f"{s}")
s, r = g("POST", "/auth/login", {"email": em, "password": pw}); at = r.get("access_token"); H = {"Authorization": "Bearer " + (at or "x")}
rec(J+".pay.login", "customer logs in", bool(at), f"{s}")
s, r = g("GET", "/payments/ops/status", None, H); rec(J+".pay.ops_forbidden", "customer cannot read ops status (403)", s == 403, f"{s}")
s, r = g("POST", "/orders", {"total": "19.99", "status": "pending"}, H); rec(J+".pay.order_forbidden", "customer cannot create order (roles)", s == 403, f"{s}")
def setroles(rl): sh("docker", "exec", "bb-final-pg", "psql", "-U", "builder", "-d", dbn, "-c", f"update auth_users set roles='{rl}'::jsonb where email='{em}'")
setroles('["admin"]'); s, r = g("POST", "/auth/login", {"email": em, "password": pw}); HA = {"Authorization": "Bearer " + r.get("access_token", "x")}
s, r = g("POST", "/orders", {"total": "19.99", "status": "pending"}, HA); rec(J+".pay.order_create", "admin creates order", s == 201, f"{s} {json.dumps(r)[:150]}")
s, rr = g("GET", "/payments/ops/status", None, HA); rec(J+".pay.ops_admin", "admin can read ops status", s == 200, f"{s} {json.dumps(rr)[:150]}")
setroles('["customer"]'); s, r2 = g("POST", "/auth/login", {"email": em, "password": pw}); H = {"Authorization": "Bearer " + r2.get("access_token", "x")}
oid = r.get("id")
s, r = g("POST", "/payments", {"payable_id": oid}); rec(J+".pay.anon", "start payment anonymous 401", s == 401, f"{s}")
if oid:
    s, r = g("POST", "/payments", {"payable_id": oid}, {**H, "Idempotency-Key": "k1-" + RUN + "-aaaa"}); rec(J+".pay.start", "start real Stripe test Checkout", s == 201 and "checkout.stripe.com" in json.dumps(r), f"{s} {redact(json.dumps(r))[:300]}")
    pay = r
    s, r = g("POST", "/payments", {"payable_id": oid, "amount_minor": 1}, {**H, "Idempotency-Key": "k2-" + RUN + "-aaaa"}); rec(J+".pay.amount_client", "client-supplied amount refused (extra forbid)", s == 422, f"{s}")
    s, r = g("POST", "/payments", {"payable_id": oid, "success_url": "https://evil.example.com/x"}, {**H, "Idempotency-Key": "k3-" + RUN + "-aaaa"}); rec(J+".pay.open_redirect", "success_url outside allow-list refused", s in (400, 422), f"{s} {json.dumps(r)[:150]}")
    s, r = g("POST", "/payments", {"payable_id": str(uuid.uuid4())}, {**H, "Idempotency-Key": "k4-" + RUN + "-aaaa"}); rec(J+".pay.unknown_payable", "unknown payable 404", s == 404, f"{s}")
    s, r = g("POST", "/payments", {"payable_id": oid}, {**H, "Idempotency-Key": "k1-" + RUN + "-aaaa"}); rec(J+".pay.idem", "same Idempotency-Key replays the same payment (no second Stripe session)", s in (200, 201) and r.get("id") == pay.get("id"), f"{s}")
    s, r = g("GET", f"/payments/{pay.get('id')}", None, H); rec(J+".pay.get", "get own payment", s == 200, f"{s}")
    # second customer must not see it
    em2 = f"v{RUN}@example.com"; g("POST", "/auth/register", {"email": em2, "password": pw}); m2 = mail_for(em2); g("POST", "/auth/email/verify", {"token": tok_from(m2)})
    s, r = g("POST", "/auth/login", {"email": em2, "password": pw}); H2 = {"Authorization": "Bearer " + r.get("access_token", "x")}
    s, r = g("GET", f"/payments/{pay.get('id')}", None, H2); rec(J+".pay.idor", "other customer cannot read my payment (404/403)", s in (403, 404), f"{s}")
    s, r = g("POST", "/payments", {"payable_id": oid}, {**H2, "Idempotency-Key": "k5-" + RUN + "-aaaa"}); rec(J+".pay.idor_start", "other customer cannot pay my order", s in (403, 404), f"{s}")
body = json.dumps({"id": "evt_" + RUN, "object": "event", "type": "checkout.session.completed", "data": {"object": {"id": "cs_x"}}}).encode()
def post_wh(sig):
    rq = urllib.request.Request(base + "/payments/webhooks/stripe", body, {"Content-Type": "application/json", "Stripe-Signature": sig}, method="POST")
    try: x = urllib.request.urlopen(rq, timeout=30); return x.status, x.read()
    except urllib.error.HTTPError as e: return e.code, e.read()
s1, b1 = post_wh("t=1,v1=" + "0" * 64); rec(J+".pay.wh_forged", "forged webhook signature rejected", s1 in (400, 401, 403, 404), f"{s1} {b1[:100]}")
s2, b2 = post_wh("garbage"); rec(J+".pay.wh_garbage", "garbage signature header rejected, generic body", s2 in (400, 401, 403, 404) and s2 == s1, f"{s2} {b2[:100]}")
ts = int(time.time()); sig = hmac.new(extra["STRIPE_WEBHOOK_SECRETS"].encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
s3, b3 = post_wh(f"t={ts},v1={sig}"); rec(J+".pay.wh_valid", "validly signed webhook accepted for unknown session (200/2xx or clean ignore)", s3 < 500, f"{s3} {b3[:100]}")
ts = int(time.time()) - 4000; sig = hmac.new(extra["STRIPE_WEBHOOK_SECRETS"].encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
s4, b4 = post_wh(f"t={ts},v1={sig}"); rec(J+".pay.wh_stale", "stale (replayed, >tolerance) timestamp rejected", s4 in (400, 401, 403, 404), f"{s4}")
s, r = g("GET", "/files/status", None, H); rec(J+".store.status", "storage status endpoint answers", s < 500, f"{s} {json.dumps(r)[:200]}")
s, r = g("GET", "/files", None, H); rec(J+".store.list", "list files (no S3 needed)", s < 500, f"{s}")
s, r = g("GET", "/files"); rec(J+".store.anon", "files anonymous 401", s == 401, f"{s}")
