from lib import *
E_ = bb.env(); PRICES = json.loads(E_["BUILDER_STRIPE_PRICE_IDS"])
ST = A.staff("admin")
oe, ot = user("sown")
c, org, _ = call(ot, "POST", "/orgs", {"name": "BBF Stripe " + RUN}); slug, oid = org["slug"], org["id"]
SUB = "sub_bbf_" + RUN; CUS = "cus_bbf_" + RUN
def wh(t, obj, **kw): return bb.stripe_webhook(t, obj, **kw)
def plan(): 
    b = call(ot, "GET", f"/orgs/{slug}/plan")[1]; return b["subscription"]["plan_id"], b["subscription"]["status"], b
now = int(time.time())
# checkout (real Stripe test mode)
c, b, _ = call(ot, "GET", f"/orgs/{slug}/plan"); rec("J7.00", "plan endpoint reports checkout_available", b.get("checkout_available") is True, str({k: b.get(k) for k in ("checkout_available", "portal_available")}))
c, b, _ = call(ot, "POST", f"/orgs/{slug}/billing/checkout", {"plan_id": "team"}); 
rec("J7.01", "owner starts Checkout for team (real Stripe test mode)", c == 200 and "checkout.stripe.com" in json.dumps(b), f"HTTP {c} {redact(json.dumps(b))[:300]}")
c, b, _ = call(ot, "POST", f"/orgs/{slug}/billing/checkout", {"plan_id": "free"}); rec("J7.02", "checkout for non-purchasable plan refused", c in (400, 409, 422), f"HTTP {c}")
c, b, _ = call(ot, "POST", f"/orgs/{slug}/billing/checkout", {"plan_id": "enterprise"}); rec("J7.03", "checkout for hidden enterprise plan refused", c in (400, 422), f"HTTP {c}")
c, b, _ = call(ot, "POST", f"/orgs/{slug}/billing/checkout", {"plan_id": "nope"}); rec("J7.04", "checkout unknown plan refused", c in (400, 404, 422), f"HTTP {c}")
ue, ut = user("sout"); c, b, _ = call(ut, "POST", f"/orgs/{slug}/billing/checkout", {"plan_id": "team"}); rec("J7.05", "outsider cannot start checkout", c in (403, 404), f"HTTP {c}")
c, b, _ = call(ot, "POST", f"/orgs/{slug}/billing/portal"); rec("J7.06", "portal without a Stripe customer -> clean 4xx", 400 <= c < 500, f"HTTP {c} {json.dumps(b)[:150]}")
# webhook auth
s, b = bb.stripe_webhook("customer.subscription.updated", {"id": SUB}, secret="whsec_forged"); rec("J7.10", "forged signature rejected", s in (400, 401, 403), f"{s}")
s, b = wh("customer.subscription.updated", {"id": SUB}, timestamp=now - 4000); rec("J7.11", "stale timestamp (replay) rejected", s in (400, 401, 403), f"{s}")
s, b = wh("customer.subscription.updated", {"id": SUB}, livemode=True); rec("J7.12", "livemode event on a test platform not applied / unknown org", s < 500, f"{s} {b[:80]}")
s, b = wh("ping.unknown", {"x": 1}); rec("J7.13", "unhandled event type acknowledged", s == 200, f"{s}")
s, b = wh("checkout.session.completed", "notadict"); rec("J7.14", "malformed event acknowledged, not 500", s < 500, f"{s}")
s, b = wh("customer.subscription.updated", {"id": "sub_unknown", "customer": "cus_unknown"}); rec("J7.15", "event for unknown org acknowledged (200)", s == 200, f"{s}")
# happy path
p0 = plan()[:2]
s, b = wh("checkout.session.completed", {"mode": "subscription", "client_reference_id": oid, "customer": CUS, "subscription": SUB, "payment_status": "paid", "metadata": {"plan_id": "team", "organization_id": oid}}, timestamp=now - 100)
pl = plan(); rec("J7.20", "checkout.session.completed -> team/active", s == 200 and pl[:2] == ("team", "active"), f"{s} {pl[:2]} (was {p0})")
evid = "evt_dup_" + RUN
sub_ev = {"id": SUB, "customer": CUS, "status": "active", "metadata": {"organization_id": oid}, "items": {"data": [{"price": {"id": PRICES["team"]}, "quantity": 3, "current_period_end": now + 86400 * 30}]}, "current_period_end": now + 86400 * 30}
s, b = wh("customer.subscription.updated", sub_ev, event_id=evid, timestamp=now - 90); rec("J7.21", "subscription.updated applied", s == 200 and plan()[0] == "team", f"{s}")
s, b = wh("customer.subscription.updated", sub_ev, event_id=evid, timestamp=now - 90); rec("J7.22", "duplicate event id idempotent", s == 200, f"{s} {b[:80]}")
cs = call(ot, "GET", f"/orgs/{slug}/audit?limit=50")[1]
n_applied = sum(1 for i in cs.get("items", []) if "stripe" in i.get("action", "") and i.get("target_id") == evid)
rec("J7.23", "duplicate event recorded once in audit", n_applied == 1, f"n={n_applied}")
bus = dict(sub_ev, items={"data": [{"price": {"id": PRICES["business"]}, "quantity": 3, "current_period_end": now + 86400 * 30}]})
s, b = wh("customer.subscription.updated", bus, timestamp=now - 80); rec("J7.24", "upgrade to business via price id", plan()[0] == "business", f"{plan()[:2]}")
s, b = wh("customer.subscription.updated", sub_ev, timestamp=now - 200); rec("J7.25", "out-of-order older event ignored (stale)", plan()[0] == "business", f"{plan()[:2]}")
c, b, _ = call(ot, "GET", f"/orgs/{slug}/plan"); rec("J7.26", "plan response exposes business limits", b["plan"]["max_seats"] == 25, str(b["plan"]["max_seats"]))
# SSO flag now allowed on business?
c, b, _ = call(ot, "GET", f"/orgs/{slug}/sso"); rec("J7.27", "business plan: SSO config readable (allow_sso)", c == 200, f"HTTP {c}")
# past due
inv = {"customer": CUS, "subscription": SUB, "parent": {"subscription_details": {"subscription": SUB}}, "lines": {"data": [{"subscription": SUB}]}}
s, b = wh("invoice.payment_failed", inv, timestamp=now - 60); pl = plan(); rec("J7.30", "invoice.payment_failed -> past_due", pl[1] == "past_due", f"{pl[:2]}")
c, b, _ = call(ot, "GET", f"/orgs/{slug}/plan"); rec("J7.31", "plan payload exposes status for the past_due banner", b["subscription"]["status"] == "past_due", "")
c, b, _ = call(ot, "POST", "/projects", {"name": "pastdue-" + RUN, "organization_id": oid}); rec("J7.32", "past_due org: creating a project is blocked or allowed (record behaviour)", True, f"HTTP {c} {json.dumps(b)[:150]}")
c, b, _ = call(ot, "POST", f"/orgs/{slug}/invitations", {"email": f"pd-{RUN}@dumbpotato.com", "role": "member"}); rec("J7.33", "past_due org: inviting (record behaviour)", True, f"HTTP {c} {json.dumps(b)[:150]}")
s, b = wh("customer.subscription.updated", dict(bus, status="active"), timestamp=now - 40); pl = plan(); rec("J7.34", "recovery: subscription active again -> active", pl[1] == "active", f"{pl[:2]}")
s, b = wh("customer.subscription.updated", dict(bus, status="past_due"), timestamp=now - 30); rec("J7.35", "subscription.updated past_due", plan()[1] == "past_due", f"{plan()[:2]}")
s, b = wh("customer.subscription.updated", dict(bus, status="unpaid"), timestamp=now - 25); rec("J7.36", "status unpaid handled", s == 200, f"{plan()[:2]}")
s, b = wh("customer.subscription.updated", dict(bus, status="active"), timestamp=now - 20)
# customer mismatch
s, b = wh("customer.subscription.updated", dict(bus, customer="cus_other"), timestamp=now - 10); rec("J7.40", "event with a different Stripe customer not applied", plan()[0] == "business" and s == 200, f"{s}")
# cancellation
s, b = wh("customer.subscription.deleted", bus, timestamp=now - 5); pl = plan(); rec("J7.50", "subscription.deleted -> free/canceled", pl[0] == "free", f"{pl[:2]}")
c, b, _ = call(ot, "POST", f"/orgs/{slug}/billing/portal"); rec("J7.51", "portal after cancel: clean response", c < 500, f"HTTP {c}")
# trial
s, b = wh("customer.subscription.created", dict(sub_ev, id="sub_trial_" + RUN, status="trialing", trial_end=now + 86400 * 14), timestamp=now - 1)
pl = plan(); rec("J7.60", "trialing subscription event handled (record plan/status)", s == 200, f"{pl[:2]} {call(ot,'GET',f'/orgs/{slug}/plan')[1]['subscription'].get('trial_ends_at')}")
# reconcile
c, b, _ = A.call("POST", "/admin/billing/reconcile", {}, ST); rec("J7.70", "operator reconcile job runs", c in (200, 202), f"HTTP {c} {json.dumps(b)[:200]}")
c, b, _ = call(ot, "POST", "/admin/billing/reconcile", {}); rec("J7.71", "customer cannot run reconcile", c in (401, 403), f"HTTP {c}")
# operator subscriptions view
c, b, _ = A.call("GET", "/admin/subscriptions", None, ST); rec("J7.72", "operator subscriptions list", c == 200, f"HTTP {c}")
c, b, _ = A.call("GET", "/admin/insights", None, ST); rec("J7.73", "operator insights", c == 200, f"HTTP {c}")
# stripe CLI
import subprocess
r = subprocess.run([os.path.expanduser("~/.stripe/bin/stripe"), "--version"], capture_output=True, text=True); rec("J7.80", "stripe CLI present", r.returncode == 0, r.stdout.strip()[:60])
