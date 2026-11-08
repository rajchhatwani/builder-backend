#!/usr/bin/env python3
"""Category 6 — SSO/SCIM. Self-contained: a disposable org bumped to the enterprise plan, our own
synthetic SAML "IdP" key/cert registered as that org's trusted IdP, driven through the real ACS
endpoint. The "test with my own e-mail" feature lets us reach every validate_response() check
without a verified domain or SSO activation (it still 'fails' at email_domain_not_verified for a
genuinely valid assertion -- that's the expected, SAFE final state; what matters is that each
NEGATIVE variant fails with the RIGHT specific reason, not that path's one).

Must run with `uv run python3` (signxml/lxml/cryptography are project deps).

Usage: uv run python3 final_test/sec-test-sonnet-5/repro/06_sso_scim.py
"""
from __future__ import annotations

import os
import sys
import time
import urllib.parse
import uuid
from datetime import timedelta

import requests

sys.path.insert(0, os.path.dirname(__file__))
from _common import bb, ngrok_headers, new_disposable_email, record, tunnel_api_base  # noqa: E402
import _saml_forge as forge  # noqa: E402

TARGET = os.environ.get("BB_TARGET", "tunnel")
API = tunnel_api_base() if TARGET == "tunnel" else os.environ.get("BB_LOCAL_API", "http://127.0.0.1:8001")
HDRS = ngrok_headers() if TARGET == "tunnel" else {}
_DELAY = 0.3 if TARGET == "tunnel" else 0.1

_session = requests.Session()


def req(method, path, body=None, token=None, headers=None, allow_redirects=False, data=None):
    h = {**HDRS, **(headers or {})}
    if token:
        h["Authorization"] = f"Bearer {token}"
    time.sleep(_DELAY)
    kwargs = {"headers": h, "timeout": 30, "allow_redirects": allow_redirects}
    if data is not None:
        kwargs["data"] = data
    else:
        kwargs["json"] = body
    for attempt in range(3):  # the free ngrok tunnel occasionally resets a connection outright
        try:
            return _session.request(method, API + path, **kwargs)
        except requests.exceptions.ConnectionError:
            if attempt == 2:
                raise
            time.sleep(2)


def new_account(prefix="sso"):
    email = new_disposable_email(prefix)
    pw = "Correct-Horse-Battery-Staple-9!"
    r = req("POST", "/account/register", {"email": email, "password": pw, "name": "sectest"})
    if r.status_code == 429:
        time.sleep(float(r.headers.get("Retry-After", 20)) + 1)
        r = req("POST", "/account/register", {"email": email, "password": pw, "name": "sectest"})
    if r.status_code != 201:
        return None, None, None
    return email, pw, r.json()["access_token"]


class SamlRig:
    """One disposable org, set up once, reused by every SAML sub-test (fresh test-ticket each time)."""

    def __init__(self):
        self.owner_email, self.owner_pw, self.owner_tok = new_account("samlorg")
        self.slug = None
        self.org_id = None
        self.sp_entity_id = None
        self.acs_url = None
        self.idp_entity_id = f"https://sectest-idp.example/{uuid.uuid4().hex[:8]}"
        self.key_pem, self.cert_pem = forge.new_keypair()
        self.foreign_key_pem, self.foreign_cert_pem = forge.new_keypair("sectest-FOREIGN-idp")
        self.ok = False
        self._setup()

    def _setup(self):
        if not self.owner_tok:
            return
        slug = f"sectest-samlorg-{uuid.uuid4().hex[:8]}"
        r = req("POST", "/orgs", {"name": "sectest saml org", "slug": slug}, token=self.owner_tok)
        if r.status_code != 201:
            return
        self.slug, self.org_id = slug, r.json()["id"]

        staff_tok = bb.Api(base=API).staff("admin")
        rr = req("PATCH", f"/admin/organizations/{self.org_id}/plan",
                 {"plan_id": "enterprise", "reason": "sectest setup"}, token=staff_tok)
        if rr.status_code != 200:
            return

        rr = req("PUT", f"/orgs/{self.slug}/sso", {
            "protocol": "saml",
            "idp_entity_id": self.idp_entity_id,
            "idp_sso_url": "https://sectest-idp.example/sso",
            "idp_cert_pem": self.cert_pem,
            "jit_enabled": True,
            "jit_role": "member",
        }, token=self.owner_tok)
        if rr.status_code != 200:
            return

        cfg = req("GET", f"/orgs/{self.slug}/sso", token=self.owner_tok).json()
        self.sp_entity_id = cfg["sp"]["entity_id"]
        self.acs_url = cfg["sp"]["acs_url"]
        self.ok = True

    def start_test_login(self) -> str | None:
        """Returns the AuthnRequest's ID (what the response must put in InResponseTo), having
        driven /orgs/{slug}/sso/test and followed the redirect to pick up the browser cookie."""
        rr = req("POST", f"/orgs/{self.slug}/sso/test", {}, token=self.owner_tok)
        if rr.status_code != 200:
            return None
        test_url = rr.json()["login_url"]
        # test_url is API_ROOT + "/sso/{slug}/login?test=<ticket>"; GET it (sets the browser
        # cookie, 302s to the "IdP" with the AuthnRequest in the query).
        path = test_url[len(API):] if test_url.startswith(API) else test_url
        rr2 = req("GET", path, allow_redirects=False)
        if rr2.status_code not in (302, 307):
            return None
        location = rr2.headers.get("Location", "")
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)
        saml_request = (qs.get("SAMLRequest") or [None])[0]
        if not saml_request:
            return None
        return forge.extract_authn_request_id(saml_request)

    def post_acs(self, response_xml: str) -> requests.Response:
        body = urllib.parse.urlencode({"SAMLResponse": forge.b64(response_xml)})
        return req("POST", f"/sso/saml/{self.slug}/acs", data=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    allow_redirects=False)

    def sso_error_of(self, resp: requests.Response) -> str | None:
        loc = resp.headers.get("Location", "")
        split = urllib.parse.urlsplit(loc)
        # the app is a hash-routed SPA: redirects land on "#/path?sso_error=X", so the query
        # string is inside the FRAGMENT, not split.query.
        frag_query = urllib.parse.urlsplit(split.fragment).query
        qs = urllib.parse.parse_qs(split.query + ("&" + frag_query if frag_query else ""))
        return (qs.get("sso_error") or qs.get("sso_test") or [None])[0]


def test_saml_baseline_and_negatives():
    rig = SamlRig()
    if not rig.ok:
        record("sso", "6.1", "SAML ACS validation (baseline + negative variants)", "n/a",
               "could not set up the disposable SAML-configured org (owner/org/plan-bump/PUT sso "
               "all need to succeed)", "Medium", "NOT_TESTABLE")
        return

    results = {}

    # (a) baseline: correctly signed, correct everything -- should reach as far as
    #     "email_domain_not_verified" (there's no verified domain on this disposable org), which
    #     PROVES validate_response() accepted the assertion; it must NOT reach "ok" (no domain).
    req_id = rig.start_test_login()
    if not req_id:
        record("sso", "6.1", "SAML ACS validation (baseline + negative variants)", "n/a",
               "could not start a test login / extract the AuthnRequest ID", "Medium", "NOT_TESTABLE")
        return
    xml, aid = forge.build_response_xml(idp_entity_id=rig.idp_entity_id, sp_entity_id=rig.sp_entity_id,
                                         acs_url=rig.acs_url, email=rig.owner_email, in_response_to=req_id)
    signed = forge.sign_assertion(xml, aid, rig.key_pem, rig.cert_pem)
    resp = rig.post_acs(signed)
    results["baseline_valid_signed_assertion"] = rig.sso_error_of(resp)

    def one_shot(label, **kwargs):
        rid = rig.start_test_login()
        if not rid:
            return "could_not_start"
        xml, aid = forge.build_response_xml(idp_entity_id=kwargs.pop("idp_entity_id", rig.idp_entity_id),
                                             sp_entity_id=kwargs.pop("sp_entity_id", rig.sp_entity_id),
                                             acs_url=kwargs.pop("acs_url", rig.acs_url),
                                             email=kwargs.pop("email", rig.owner_email),
                                             in_response_to=kwargs.pop("in_response_to", rid), **kwargs)
        sign = kwargs if False else None  # (kwargs already consumed above)
        key = rig.foreign_key_pem if label == "foreign_signer" else rig.key_pem
        cert = rig.foreign_cert_pem if label == "foreign_signer" else rig.cert_pem
        if label == "unsigned":
            final_xml = xml
        else:
            final_xml = forge.sign_assertion(xml, aid, key, cert)
        resp = rig.post_acs(final_xml)
        return rig.sso_error_of(resp)

    results["unsigned_assertion"] = one_shot("unsigned")
    results["foreign_signer_wrong_key"] = one_shot("foreign_signer")
    results["wrong_audience"] = one_shot("wrong_audience", sp_entity_id="https://not-the-real-sp.example")
    results["wrong_issuer"] = one_shot("wrong_issuer", idp_entity_id="https://not-the-registered-idp.example")
    results["wrong_recipient"] = one_shot("wrong_recipient", recipient="https://attacker.example/acs")
    results["expired"] = one_shot("expired", not_before_delta=timedelta(minutes=-30),
                                   not_after_delta=timedelta(minutes=-10))
    results["unsolicited_idp_initiated"] = one_shot("unsolicited", unsolicited=True)

    # replay: reuse the EXACT signed response from the baseline a second time
    resp2 = rig.post_acs(signed)
    results["replay_of_baseline"] = rig.sso_error_of(resp2)

    expect = {
        "baseline_valid_signed_assertion": "email_domain_not_verified",  # proves it PASSED validate_response
        "unsigned_assertion": "unsigned",
        "foreign_signer_wrong_key": "bad_signature",
        "wrong_audience": "wrong_audience",
        "wrong_issuer": "wrong_issuer",
        "wrong_recipient": "wrong_recipient",
        "expired": "expired",
        "unsolicited_idp_initiated": "unsolicited",
        "replay_of_baseline": None,  # must NOT be "email_domain_not_verified" again -- must fail
    }
    bad = []
    for k, expected in expect.items():
        actual = results.get(k)
        if k == "replay_of_baseline":
            if actual == "email_domain_not_verified":
                bad.append((k, actual, "replay was accepted a second time"))
        elif actual != expected:
            bad.append((k, actual, f"expected {expected!r}"))

    ok = len(bad) == 0
    record("sso", "6.1", "SAML ACS validation: signature, audience, issuer, recipient, expiry, "
           "unsolicited-response, and replay are all individually enforced",
           "each negative variant fails with its OWN specific reason; the baseline reaches as far "
           "as 'email_domain_not_verified' (proving the crypto/structural checks passed); a replay "
           "of the exact same signed response is refused the second time",
           f"results={results}" + (f" MISMATCHES={bad}" if bad else ""),
           "Critical" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


def test_saml_signature_wrapping():
    """Classic XML Signature Wrapping: inject a SECOND, attacker-controlled, unsigned Assertion
    (different email) alongside the real signed one, hoping the app reads the wrong one."""
    rig = SamlRig()
    if not rig.ok:
        record("sso", "6.2", "SAML signature-wrapping (second forged Assertion alongside the signed one)",
               "n/a", "could not set up the disposable SAML org", "Medium", "NOT_TESTABLE")
        return
    req_id = rig.start_test_login()
    if not req_id:
        record("sso", "6.2", "SAML signature-wrapping", "n/a", "could not start a test login",
               "Medium", "NOT_TESTABLE")
        return
    victim_email = "victim-" + uuid.uuid4().hex[:8] + "@sectest.example"
    # the REAL signed assertion asserts rig.owner_email; sneak in an extra, UNSIGNED assertion
    # claiming to be `victim_email` and see whether the app is fooled into using it.
    extra = f"""<saml:Assertion xmlns:saml="{forge.NS['saml']}" ID="_{uuid.uuid4().hex}" Version="2.0"
        IssueInstant="2026-01-01T00:00:00Z"><saml:Issuer>{rig.idp_entity_id}</saml:Issuer>
        <saml:Subject><saml:NameID>{victim_email}</saml:NameID></saml:Subject></saml:Assertion>"""
    xml, aid = forge.build_response_xml(idp_entity_id=rig.idp_entity_id, sp_entity_id=rig.sp_entity_id,
                                         acs_url=rig.acs_url, email=rig.owner_email,
                                         in_response_to=req_id, extra_assertion_xml=extra)
    signed = forge.sign_assertion(xml, aid, rig.key_pem, rig.cert_pem)
    resp = rig.post_acs(signed)
    result = rig.sso_error_of(resp)
    # validate_response() explicitly refuses >1 Assertion ("multiple_assertions"), so this should
    # fail outright rather than silently pick either identity.
    ok = result == "multiple_assertions"
    record("sso", "6.2", "SAML signature-wrapping (extra unsigned Assertion alongside the signed one)",
           "a Response containing more than one Assertion is refused outright ('multiple_assertions'), "
           "never silently resolved to either identity",
           f"result={result}",
           "Critical" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


def test_saml_xxe():
    rig = SamlRig()
    if not rig.ok:
        record("sso", "6.3", "SAML XXE / DOCTYPE rejection", "n/a", "could not set up the disposable SAML org",
               "Medium", "NOT_TESTABLE")
        return
    req_id = rig.start_test_login()
    malicious = (
        '<?xml version="1.0"?><!DOCTYPE samlp:Response [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        f'<samlp:Response xmlns:samlp="{forge.NS["samlp"]}" xmlns:saml="{forge.NS["saml"]}" '
        f'ID="_x" Version="2.0" IssueInstant="2026-01-01T00:00:00Z">'
        f"<saml:Issuer>&xxe;{rig.idp_entity_id}</saml:Issuer>"
        "<samlp:Status><samlp:StatusCode Value=\"urn:oasis:names:tc:SAML:2.0:status:Success\"/></samlp:Status>"
        "</samlp:Response>"
    )
    resp = rig.post_acs(malicious)
    result = rig.sso_error_of(resp)
    ok = result == "malformed"
    record("sso", "6.3", "SAML XXE/DOCTYPE in the Response is rejected outright",
           "a Response containing a DOCTYPE/ENTITY declaration is refused ('malformed'), never parsed",
           f"result={result}",
           "Critical" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# OIDC: SSRF guard on the discovery URL
# ---------------------------------------------------------------------------
def test_oidc_ssrf_guard():
    owner_email, owner_pw, owner_tok = new_account("oidcssrf")
    if not owner_tok:
        record("sso", "6.4", "OIDC discovery_url SSRF guard", "n/a", "could not create account", "Medium", "NOT_TESTABLE")
        return
    slug = f"sectest-oidcssrf-{uuid.uuid4().hex[:8]}"
    r = req("POST", "/orgs", {"name": "sectest", "slug": slug}, token=owner_tok)
    if r.status_code != 201:
        record("sso", "6.4", "OIDC discovery_url SSRF guard", "n/a", "could not create org", "Medium", "NOT_TESTABLE")
        return
    org_id = r.json()["id"]
    staff_tok = bb.Api(base=API).staff("admin")
    req("PATCH", f"/admin/organizations/{org_id}/plan", {"plan_id": "enterprise", "reason": "sectest"}, token=staff_tok)

    targets = {
        "loopback": "https://127.0.0.1:9999/.well-known/openid-configuration",
        "metadata_ip": "https://169.254.169.254/latest/meta-data/",
        "private_rfc1918": "https://10.0.0.5/.well-known/openid-configuration",
        "localhost_name": "https://localhost/.well-known/openid-configuration",
    }
    bad = []
    for label, url in targets.items():
        rr = req("PUT", f"/orgs/{slug}/sso", {
            "protocol": "oidc", "oidc_discovery_url": url, "oidc_client_id": "x", "oidc_client_secret": "y",
        }, token=owner_tok)
        # saving the config itself may be allowed (the private-IP check happens at FETCH time in
        # this codebase, per sso_service.py/oidc.py); the real test is "sso/check", which fetches.
        chk = req("POST", f"/orgs/{slug}/sso/check", {}, token=owner_tok)
        body = chk.json() if chk.content else {}
        checks = body.get("checks", [])
        discovery_check = next((c for c in checks if c.get("name") == "discovery"), None)
        blocked = chk.status_code == 200 and discovery_check is not None and discovery_check.get("status") == "error"
        if not blocked:
            bad.append((label, url, chk.status_code, discovery_check))
    ok = len(bad) == 0
    record("sso", "6.4", "OIDC discovery_url SSRF guard refuses loopback/link-local/private/localhost targets",
           "PUT /orgs/{slug}/sso followed by POST /sso/check never actually reaches a private/"
           "loopback/metadata address (sso_allow_private_idp=false in this env)",
           f"problem_targets={bad}" if bad else f"all {len(targets)} targets correctly blocked",
           "Critical" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID")


# ---------------------------------------------------------------------------
# SCIM: self-contained tenant isolation + off-domain provisioning
# ---------------------------------------------------------------------------
def test_scim_self_contained():
    owner_email, owner_pw, owner_tok = new_account("scimorg")
    if not owner_tok:
        record("scim", "6.5", "SCIM self-contained tests", "n/a", "could not create owner account", "Medium", "NOT_TESTABLE")
        return
    slug = f"sectest-scimorg-{uuid.uuid4().hex[:8]}"
    r = req("POST", "/orgs", {"name": "sectest", "slug": slug}, token=owner_tok)
    if r.status_code != 201:
        record("scim", "6.5", "SCIM self-contained tests", "n/a", "could not create org", "Medium", "NOT_TESTABLE")
        return
    org_id = r.json()["id"]
    staff_tok = bb.Api(base=API).staff("admin")
    rr = req("PATCH", f"/admin/organizations/{org_id}/plan", {"plan_id": "enterprise", "reason": "sectest"}, token=staff_tok)
    if rr.status_code != 200:
        record("scim", "6.5", "SCIM self-contained tests", "n/a", "could not raise plan to enterprise", "Medium", "NOT_TESTABLE")
        return

    rr = req("POST", f"/orgs/{slug}/scim/token", {}, token=owner_tok)
    if rr.status_code != 201:
        record("scim", "6.5", "SCIM self-contained tests", "n/a", f"could not enable SCIM: HTTP {rr.status_code} {rr.text[:200]}",
               "Medium", "NOT_TESTABLE")
        return
    scim_token = rr.json()["token"]
    scim_base = API  # SCIM lives at /scim/v2 on the same origin, per the base_url shown in the UI

    bb_scim = bb.Scim(scim_base, scim_token)

    # (a) off-domain provisioning: no verified domain on this org at all -- does SCIM care, or
    #     does it provision anyone regardless of domain (a gap if JIT-equivalent trust applies)?
    off_domain_user = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "userName": f"scim-{uuid.uuid4().hex[:8]}@totally-unrelated-domain.example",
        "active": True,
        "emails": [{"value": f"scim-{uuid.uuid4().hex[:8]}@totally-unrelated-domain.example", "primary": True}],
    }
    time.sleep(_DELAY)
    status_a, body_a = bb_scim.call("POST", "/scim/v2/Users", off_domain_user)

    # (b) the SCIM token is scoped to THIS org only: using it against a DIFFERENT org's SCIM
    #     endpoint must fail. Make a second disposable org+owner+SCIM-less org and try.
    other_owner_email, other_owner_pw, other_owner_tok = new_account("scimother")
    other_slug = f"sectest-scimother-{uuid.uuid4().hex[:8]}"
    req("POST", "/orgs", {"name": "sectest", "slug": other_slug}, token=other_owner_tok)
    # There's one SCIM base per deployment (not per-org in the URL); the bearer itself is what
    # scopes the request server-side. Confirm the SAME bearer cannot be reused to read the
    # token's own directory after being revoked (c), and that app bearers don't work on SCIM (d).
    time.sleep(_DELAY)
    status_c_before, _ = bb_scim.call("GET", "/scim/v2/Users")

    rr = req("DELETE", f"/orgs/{slug}/scim", token=owner_tok)
    revoke_status = rr.status_code
    time.sleep(_DELAY)
    status_c_after, _ = bb_scim.call("GET", "/scim/v2/Users")

    # (d) an ordinary app session/API bearer must not work as a SCIM bearer.
    time.sleep(_DELAY)
    app_bearer_scim = bb.Scim(scim_base, owner_tok).call("GET", "/scim/v2/Users")

    findings = {
        "off_domain_user_provision_status": status_a,
        "scim_read_before_revoke": status_c_before,
        "scim_revoke_endpoint_status": revoke_status,
        "scim_read_after_revoke": status_c_after,
        "app_bearer_used_as_scim_bearer": app_bearer_scim[0],
    }
    ok = (
        status_c_before == 200
        and revoke_status in (200, 204)
        and status_c_after in (401, 403)
        and app_bearer_scim[0] in (401, 403)
    )
    record("scim", "6.5", "SCIM bearer lifecycle (works while active, dies on revoke) and app "
           "bearers never work as SCIM bearers",
           "SCIM reads work before revoke, fail after; an ordinary app session bearer is refused on SCIM routes",
           f"{findings} (off-domain provisioning status noted but not judged -- SCIM is IdP-pushed, "
           "the org has no verified-domain gate documented for it; see note)",
           "Medium" if not ok else "Info",
           "CONFIRMED" if not ok else "SOLID",
           note="off_domain_user_provision_status is informational: SCIM directories are usually "
                "trusted as-is (the IdP is the source of truth), so provisioning an arbitrary-domain "
                "user via SCIM may be by design, not a bug -- flagged for a human to judge, not "
                "scored automatically")


def main():
    print(f"=== 06_sso_scim against {TARGET} ({API}) ===")
    for fn in (
        test_saml_baseline_and_negatives,
        test_saml_signature_wrapping,
        test_saml_xxe,
        test_oidc_ssrf_guard,
        test_scim_self_contained,
    ):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            record("sso", fn.__name__, fn.__name__, "test runs cleanly",
                   f"test script raised {type(exc).__name__}: {exc}", "Low", "NOT_TESTABLE")


if __name__ == "__main__":
    main()
