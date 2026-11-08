import sys, json, base64, zlib, urllib.parse, urllib.request, http.cookiejar, re
from datetime import datetime, timedelta, UTC

sys.path.insert(0, "/mnt/files/projects/builder-backend")
sys.path.insert(0, "/mnt/files/projects/builder-backend/tests")
sys.path.insert(0, "/mnt/files/projects/builder-backend/final_test/harness")
import bb
from sso_fake_idp import idp_keys, attacker_keys, saml_response_xml, sign_assertion, b64, IDP_ENTITY_ID

API = "http://127.0.0.1:8000"
TUNNEL = "https://cinderous-overfamiliar-sanford.ngrok-free.dev"
SLUG = "bb-sso"
ACS_URL = f"{TUNNEL}/sso/saml/{SLUG}/acs"

req = urllib.request.Request(f"{API}/sso/metadata/{SLUG}")
with urllib.request.urlopen(req, timeout=10) as r:
    meta_xml = r.read().decode()
sp_entity_id = re.search(r'entityID="([^"]+)"', meta_xml).group(1)
acs_url_real = re.search(r'Location="([^"]+)"', meta_xml).group(1)

keys = idp_keys()

import bb as _bb
_api = bb.Api()
_owner_tok = _api.customer("owner")
_cfg = {"protocol": "saml", "idp_entity_id": IDP_ENTITY_ID, "idp_sso_url": "https://idp.example.test/saml/sso",
        "idp_cert_pem": keys.cert_pem, "jit_enabled": True, "jit_role": "member", "trust_unverified_email": True}
_st, _b, _ = _api.call("PUT", f"/orgs/{SLUG}/sso", _cfg, token=_owner_tok)
print("re-PUT sso (fresh matching key):", _st)
_st, _b, _ = _api.call("POST", f"/orgs/{SLUG}/sso/activate", {}, token=_owner_tok)
print("re-activate:", _st)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None

def start_login():
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj), NoRedirect)
    try:
        opener.open(urllib.request.Request(f"{TUNNEL}/sso/{SLUG}/login", headers={"ngrok-skip-browser-warning": "1"}), timeout=10)
        raise RuntimeError("expected redirect, got 200")
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location")
    qs = urllib.parse.urlparse(loc).query
    saml_req_b64 = urllib.parse.parse_qs(qs)["SAMLRequest"][0]
    raw = zlib.decompress(base64.b64decode(saml_req_b64), -15)
    req_id = re.search(rb'ID="([^"]+)"', raw).group(1).decode()
    return req_id, cj

def post_acs(xml, cookiejar):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar), NoRedirect)
    data = urllib.parse.urlencode({"SAMLResponse": b64(xml)}).encode()
    r = urllib.request.Request(ACS_URL, data, {"Content-Type": "application/x-www-form-urlencoded", "ngrok-skip-browser-warning": "1"}, method="POST")
    try:
        with opener.open(r, timeout=15) as resp:
            return resp.status, resp.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location", "")

def classify(loc):
    if "sso_error" in loc or "error" in loc.lower():
        q = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
        return "REFUSED:" + (q.get("sso_error", q.get("error", ["?"]))[0])
    return "ACCEPTED" if loc else "?"

RESULTS = []

def case(name, builder, expect):
    req_id, cj = start_login()
    xml = builder(req_id)
    st, loc = post_acs(xml, cj)
    c = classify(loc)
    RESULTS.append({"case": name, "status": st, "outcome": c, "location": loc[:160], "expect": expect})
    return req_id, cj, xml

case("A_valid_signed_assertion",
     lambda rid: sign_assertion(saml_response_xml(email="bb-sso1@dumbpotato.com", sp_entity_id=sp_entity_id,
        acs_url=acs_url_real, in_response_to=rid, issuer=IDP_ENTITY_ID, recipient=acs_url_real), keys),
     "ACCEPTED")

case("B_unsigned",
     lambda rid: saml_response_xml(email="bb-sso1@dumbpotato.com", sp_entity_id=sp_entity_id,
        acs_url=acs_url_real, in_response_to=rid, issuer=IDP_ENTITY_ID, recipient=acs_url_real),
     "REFUSED")

case("C_foreign_signed_attacker_key",
     lambda rid: sign_assertion(saml_response_xml(email="bb-owner@dumbpotato.com", sp_entity_id=sp_entity_id,
        acs_url=acs_url_real, in_response_to=rid, issuer=IDP_ENTITY_ID, recipient=acs_url_real), attacker_keys()),
     "REFUSED")

case("D_wrong_audience",
     lambda rid: sign_assertion(saml_response_xml(email="bb-sso1@dumbpotato.com", sp_entity_id=sp_entity_id,
        acs_url=acs_url_real, in_response_to=rid, issuer=IDP_ENTITY_ID, recipient=acs_url_real,
        audience="https://not-us.example.test"), keys),
     "REFUSED")

case("E_wrong_recipient",
     lambda rid: sign_assertion(saml_response_xml(email="bb-sso1@dumbpotato.com", sp_entity_id=sp_entity_id,
        acs_url=acs_url_real, in_response_to=rid, issuer=IDP_ENTITY_ID, recipient="https://evil.example.test/acs"), keys),
     "REFUSED")

case("F_wrong_issuer",
     lambda rid: sign_assertion(saml_response_xml(email="bb-sso1@dumbpotato.com", sp_entity_id=sp_entity_id,
        acs_url=acs_url_real, in_response_to=rid, issuer="https://not-the-real-idp.example.test", recipient=acs_url_real), keys),
     "REFUSED")

now = datetime.now(UTC)
case("G_expired_assertion",
     lambda rid: sign_assertion(saml_response_xml(email="bb-sso1@dumbpotato.com", sp_entity_id=sp_entity_id,
        acs_url=acs_url_real, in_response_to=rid, issuer=IDP_ENTITY_ID, recipient=acs_url_real,
        now=now - timedelta(hours=1), not_on_or_after=now - timedelta(minutes=50)), keys),
     "REFUSED")

case("H_not_yet_valid",
     lambda rid: sign_assertion(saml_response_xml(email="bb-sso1@dumbpotato.com", sp_entity_id=sp_entity_id,
        acs_url=acs_url_real, in_response_to=rid, issuer=IDP_ENTITY_ID, recipient=acs_url_real,
        not_before=now + timedelta(hours=1)), keys),
     "REFUSED")

# I: unsolicited / unmatched InResponseTo (fresh login started, but we ignore its real id)
_rid_ignored, cj_i = start_login()
xml_i = sign_assertion(saml_response_xml(email="bb-sso1@dumbpotato.com", sp_entity_id=sp_entity_id,
    acs_url=acs_url_real, in_response_to="_neverissued1234567890abcdef", issuer=IDP_ENTITY_ID, recipient=acs_url_real), keys)
st_i, loc_i = post_acs(xml_i, cj_i)
RESULTS.append({"case": "I_unmatched_in_response_to", "status": st_i, "outcome": classify(loc_i), "location": loc_i[:160], "expect": "REFUSED"})

# J: replay - reuse case A's own login+signed response material by starting a NEW valid one and posting it twice
rid_j, cj_j = start_login()
xml_j = sign_assertion(saml_response_xml(email="bb-sso2@dumbpotato.com", sp_entity_id=sp_entity_id,
    acs_url=acs_url_real, in_response_to=rid_j, issuer=IDP_ENTITY_ID, recipient=acs_url_real), keys)
st_j1, loc_j1 = post_acs(xml_j, cj_j)
st_j2, loc_j2 = post_acs(xml_j, cj_j)
RESULTS.append({"case": "J_replay_same_valid_response_twice", "first": {"status": st_j1, "outcome": classify(loc_j1)},
                 "second": {"status": st_j2, "outcome": classify(loc_j2), "location": loc_j2[:160]}, "expect": "second=REFUSED"})

# K: signature wrapping - forged extra Assertion spliced in before the signed one
def wrapped(rid):
    legit = saml_response_xml(email="bb-sso1@dumbpotato.com", sp_entity_id=sp_entity_id, acs_url=acs_url_real,
                               in_response_to=rid, issuer=IDP_ENTITY_ID, recipient=acs_url_real)
    signed = sign_assertion(legit, keys)
    forged = ('<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="_forged1" Version="2.0" '
              f'IssueInstant="{datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}">'
              f'<saml:Issuer>{IDP_ENTITY_ID}</saml:Issuer>'
              '<saml:Subject><saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">'
              'bb-owner@dumbpotato.com</saml:NameID></saml:Subject></saml:Assertion>')
    marker = "</samlp:Status>"
    idx = signed.index(marker) + len(marker)
    return signed[:idx] + forged + signed[idx:]
case("K_signature_wrapping_extra_assertion", wrapped, "REFUSED")

print(json.dumps(RESULTS, indent=2, default=str))
with open("/mnt/files/projects/builder-backend/final_test/security/evidence/saml_live_results.json", "w") as f:
    json.dump(RESULTS, f, indent=2, default=str)
