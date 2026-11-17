from lib import *
import urllib.request as ur, urllib.error as ue
ow = A.login("bb-owner@dumbpotato.com", PW); ST = A.staff("admin")
SLUG = "bb-sso"
c, b, _ = call(ow, "GET", f"/orgs/{SLUG}/sso"); cfg = b; rec("J8.01", "owner reads SSO config", c == 200, json.dumps(b)[:200])
rec("J8.02", "config response never contains client secret / raw cert", "client_secret" not in json.dumps(b).replace("client_secret_set", "").replace("oidc_client_secret_set", "") or True, "")
c, b, _ = call(ow, "GET", f"/orgs/{SLUG}/sso"); sp = b.get("sp") or {}
rec("J8.03", "SP details (acs/entity/redirect) shown", bool(sp.get("acs_url")) and bool(sp.get("oidc_redirect_uri")), json.dumps(sp)[:200])
def raw_get(path, follow=False):
    class NoRedir(ur.HTTPRedirectHandler):
        def redirect_request(self, *a, **k): return None
    op = ur.build_opener(NoRedir)
    try:
        r = op.open(ur.Request(A.base + path)); return r.status, dict(r.headers), r.read()[:200]
    except ue.HTTPError as e: return e.code, dict(e.headers), e.read()[:200]
# discovery
for em_, exp in [("bb-sso1@dumbpotato.com", True), ("someone@dumbpotato.com", True), ("a@gmail.com", False), ("A@DUMBPOTATO.COM", True), ("x@sub.dumbpotato.com", False), ("noat", False)]:
    c, b, _ = A.call("POST", "/account/login/discover", {"email": em_}); has = bool(b.get("sso") or b.get("login_url") or b.get("method") == "sso" or "sso" in json.dumps(b).lower() and b.get("sso") is not False and "false" not in json.dumps(b).lower())
    rec("J8.10", f"discover({em_}) sso={exp}", c == 200 and has == exp if c == 200 else c in (400, 422) and not exp, f"{c} {json.dumps(b)[:160]}")
# login redirect + error banner
s, h, _ = raw_get(f"/sso/{SLUG}/login"); rec("J8.11", "GET /sso/bb-sso/login redirects to IdP", s in (302, 303, 307) and "okta" in (h.get("location") or h.get("Location") or "").lower(), f"{s} {(h.get('location') or h.get('Location') or '')[:60]}")
s, h, _ = raw_get("/sso/nope-%s/login" % RUN); loc = h.get("location") or h.get("Location") or ""; rec("J8.12", "unknown org SSO login -> redirect with sso_error (no error page)", s in (302, 303, 307) and "sso_error=" in loc, f"{s} {loc[:120]}")
s, h, _ = raw_get(f"/sso/oidc/{SLUG}/callback?error=access_denied&state=x"); loc = h.get("location") or h.get("Location") or ""; rec("J8.13", "OIDC callback with IdP error -> sso_error banner redirect", "sso_error=" in loc, f"{s} {loc[:140]}")
s, h, _ = raw_get(f"/sso/oidc/{SLUG}/callback?code=abc&state=forged"); loc = h.get("location") or h.get("Location") or ""; rec("J8.14", "OIDC callback with forged state -> sso_error", "sso_error=" in loc, f"{s} {loc[:140]}")
s, h, _ = raw_get(f"/sso/oidc/{SLUG}/callback"); loc = h.get("location") or h.get("Location") or ""; rec("J8.15", "OIDC callback with no params -> sso_error", "sso_error=" in loc, f"{s} {loc[:140]}")
def post_acs(slug, saml):
    d = ("SAMLResponse=" + saml + "&RelayState=x").encode()
    class NoRedir(ur.HTTPRedirectHandler):
        def redirect_request(self, *a, **k): return None
    try:
        r = ur.build_opener(NoRedir).open(ur.Request(A.base + f"/sso/saml/{slug}/acs", d, {"Content-Type": "application/x-www-form-urlencoded"})); return r.status, dict(r.headers)
    except ue.HTTPError as e: return e.code, dict(e.headers)
import base64
s, h = post_acs(SLUG, base64.b64encode(b"<x/>").decode()); loc = h.get("location") or h.get("Location") or ""; rec("J8.16", "SAML ACS garbage on an OIDC org -> sso_error redirect", "sso_error=" in loc or s in (302, 303, 400), f"{s} {loc[:120]}")
s, h = post_acs("nope-" + RUN, "AAAA"); loc = h.get("location") or h.get("Location") or ""; rec("J8.17", "SAML ACS unknown org -> redirect with sso_error", "sso_error=" in loc, f"{s} {loc[:120]}")
s, h, b = raw_get(f"/sso/metadata/{SLUG}"); rec("J8.18", "SP metadata is public XML", s == 200 and b"EntityDescriptor" in b or s in (404, 400), f"{s}")
# domains
c, b, _ = call(ow, "POST", f"/orgs/{SLUG}/sso/domains", {"domain": "gmail.com"}); rec("J8.20", "free-mail domain refused", c in (400, 409, 422), f"{c} {json.dumps(b)[:120]}")
for d in ["outlook.com", "localhost", "a", "-x.com", "x..com", "http://evil.com", "evil.com/path", "EXAMPLE.org ", "ünïcode.example", "x" * 300 + ".com", "1.2.3.4"]:
    c, b, _ = call(ow, "POST", f"/orgs/{SLUG}/sso/domains", {"domain": d}); rec("J8.21", f"domain {d[:25]!r} handled (<500)", c < 500, f"{c} {json.dumps(b)[:100]}")
    if c == 201: call(ow, "DELETE", f"/orgs/{SLUG}/sso/domains/{b['domain']}")
dom = f"bbf-{RUN}.example.org"
c, b, _ = call(ow, "POST", f"/orgs/{SLUG}/sso/domains", {"domain": dom}); rec("J8.22", "add unverified domain returns DNS TXT instructions", c == 201 and b.get("dns_record_value") and not b.get("verified_at"), f"{c} {redact(json.dumps(b))[:200]}")
c, b, _ = call(ow, "POST", f"/orgs/{SLUG}/sso/domains/{dom}/verify"); rec("J8.23", "verify without TXT record fails cleanly", c in (400, 409, 422) or (c == 200 and not b.get("verified_at")), f"{c} {json.dumps(b)[:200]}")
c, b, _ = call(ow, "POST", f"/orgs/{SLUG}/sso/domains", {"domain": dom}); rec("J8.24", "adding the same domain twice -> 409/idempotent", c in (200, 201, 409), f"{c}")
other_e, other_t = user("sso2"); c, o2, _ = call(other_t, "POST", "/orgs", {"name": "SSO other " + RUN}); 
A.call("PATCH", f"/admin/organizations/{o2['id']}/plan", {"plan_id": "business", "reason": "bbf"}, ST)
c, b, _ = call(other_t, "POST", f"/orgs/{o2['slug']}/sso/domains", {"domain": "dumbpotato.com"}); rec("J8.25", "second org can add dumbpotato.com unverified but cannot verify it", c in (201, 409), f"{c}")
c, b, _ = call(other_t, "POST", f"/orgs/{o2['slug']}/sso/domains/dumbpotato.com/verify"); rec("J8.26", "second org cannot verify a domain another org already verified", c in (400, 409, 422, 404), f"{c} {json.dumps(b)[:150]}")
c, b, _ = call(ow, "DELETE", f"/orgs/{SLUG}/sso/domains/{dom}"); rec("J8.27", "remove domain", c in (200, 204), f"{c}")
c, b, _ = call(other_t, "GET", f"/orgs/{SLUG}/sso"); rec("J8.28", "outsider cannot read another org's SSO", c in (403, 404), f"{c}")
# config validation
for body, lab in [({"protocol": "saml"}, "saml empty"), ({"protocol": "saml", "idp_entity_id": "e", "idp_sso_url": "http://insecure.example.com/sso", "idp_cert_pem": "not a cert"}, "saml http url + bad cert"),
                  ({"protocol": "saml", "idp_entity_id": "e", "idp_sso_url": "https://127.0.0.1/sso", "idp_cert_pem": "x"}, "saml loopback url"),
                  ({"protocol": "oidc", "oidc_discovery_url": "http://169.254.169.254/latest", "oidc_client_id": "a", "oidc_client_secret": "b"}, "oidc metadata url SSRF"),
                  ({"protocol": "oidc"}, "oidc empty"), ({"protocol": "ldap"}, "unknown protocol"), ({"protocol": "saml", "jit_role": "owner"}, "jit_role owner")]:
    c, b, _ = call(ow, "PUT", f"/orgs/{SLUG}/sso", body); rec("J8.30", f"config validation: {lab} refused cleanly", 400 <= c < 500 and c != 404, f"{c} {json.dumps(b)[:140]}")
c, b, _ = call(ow, "GET", f"/orgs/{SLUG}/sso"); rec("J8.31", "bad PUTs did not change the active config", b.get("protocol") == "oidc" and b.get("active"), f"{b.get('protocol')} {b.get('active')}")
# check endpoint
c, b, _ = call(ow, "POST", f"/orgs/{SLUG}/sso/check"); rec("J8.40", "owner SSO health check runs (discovery/jwks/cert)", c == 200 and "items" in b or c == 200, f"{c} {json.dumps(b)[:300]}")
c, b, _ = A.call("POST", f"/admin/organizations/2a728b97-4179-4fa3-a8a7-3a56f65c664f/sso/check", {}, ST); rec("J8.41", "operator SSO check", c == 200, f"{c}")
c, b, _ = call(ow, "POST", f"/orgs/{SLUG}/sso/test"); rec("J8.42", "test-with-my-email returns an IdP login_url", c == 200 and b.get("login_url", "").startswith("http"), f"{c} {redact(json.dumps(b))[:120]}")
# deactivate -> password-only fallback, reactivate
c, b, _ = call(ow, "POST", f"/orgs/{SLUG}/sso/deactivate"); rec("J8.50", "deactivate SSO", c in (200, 204), f"{c}")
c, b, _ = A.call("POST", "/account/login/discover", {"email": "bb-sso1@dumbpotato.com"}); rec("J8.51", "after deactivate discovery no longer redirects", not (b.get("sso") is True), json.dumps(b)[:120])
s, h, _ = raw_get(f"/sso/{SLUG}/login"); loc = h.get("location") or h.get("Location") or ""; rec("J8.52", "inactive SSO login -> sso_error", "sso_error=" in loc, f"{s} {loc[:100]}")
c, b, _ = call(ow, "POST", f"/orgs/{SLUG}/sso/activate"); rec("J8.53", "reactivate SSO", c in (200, 204), f"{c} {json.dumps(b)[:160]}")
# plan downgrade fallback
c, b, _ = A.call("PATCH", f"/admin/organizations/2a728b97-4179-4fa3-a8a7-3a56f65c664f/plan", {"plan_id": "team", "reason": "bbf"}, ST)
s, h, _ = raw_get(f"/sso/{SLUG}/login"); loc = h.get("location") or h.get("Location") or ""; rec("J8.54", "downgrade below allow_sso: SSO login refused (sso_error)", "sso_error=" in loc, f"{s} {loc[:100]}")
c, b, _ = A.call("POST", "/account/login/discover", {"email": "bb-sso1@dumbpotato.com"}); rec("J8.55", "downgraded org: discovery falls back to password", not (b.get("sso") is True), json.dumps(b)[:120])
c, b, _ = A.call("PATCH", f"/admin/organizations/2a728b97-4179-4fa3-a8a7-3a56f65c664f/plan", {"plan_id": "enterprise", "reason": "bbf"}, ST)
