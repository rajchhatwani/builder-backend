import sys, json, time, urllib.parse, urllib.request, http.cookiejar, re
from datetime import datetime, timedelta, UTC

sys.path.insert(0, "/mnt/files/projects/builder-backend")
sys.path.insert(0, "/mnt/files/projects/builder-backend/tests")
sys.path.insert(0, "/mnt/files/projects/builder-backend/final_test/harness")
import bb
from sso_fake_idp import idp_keys, attacker_keys, id_token as make_id_token, OIDC_KID

sys.path.insert(0, "/tmp/claude-1000/-mnt-files-projects-builder-backend/93af46a5-8476-4fb5-9045-ae58628efbc7/scratchpad")
import fake_oidc_idp

fake_oidc_idp.run()

API = "https://cinderous-overfamiliar-sanford.ngrok-free.dev"
SLUG = "bb-sso"
CLIENT_ID = "test-client-id"
REDIRECT_URI = f"{API}/sso/oidc/{SLUG}/callback"

keys = idp_keys()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def start_login():
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj), NoRedirect)
    try:
        opener.open(urllib.request.Request(f"{API}/sso/{SLUG}/login", headers={"ngrok-skip-browser-warning": "1"}), timeout=10)
        raise RuntimeError("expected redirect")
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
    state = q["state"][0]
    nonce = q["nonce"][0]
    return state, nonce, cj


def callback(state, code, cj):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj), NoRedirect)
    url = f"{API}/sso/oidc/{SLUG}/callback?" + urllib.parse.urlencode({"state": state, "code": code})
    try:
        with opener.open(urllib.request.Request(url, headers={"ngrok-skip-browser-warning": "1"}), timeout=10) as r:
            return r.status, r.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location", "")


def classify(loc):
    # the SPA uses hash routing: the real query string lives in the URL fragment, e.g.
    # https://host/#/login?sso_error=wrong_nonce -- urlparse().query is always empty here.
    frag = urllib.parse.urlparse(loc).fragment  # "/login?sso_error=wrong_nonce"
    q = urllib.parse.parse_qs(urllib.parse.urlparse(frag).query)
    if "sso_error" in q:
        return "REFUSED:" + q["sso_error"][0]
    return "ACCEPTED" if loc else "?"


RESULTS = []


def case(name, make_token, expect):
    state, nonce, cj = start_login()
    code = f"code-{name}-{int(time.time()*1000)}"
    token = make_token(nonce)
    fake_oidc_idp.CODES[code] = token
    st, loc = callback(state, code, cj)
    RESULTS.append({"case": name, "status": st, "outcome": classify(loc), "location": loc[:160], "expect": expect})


EMAIL = "bb-sso1@dumbpotato.com"

# A: fully valid
case(
    "A_valid",
    lambda nonce: make_id_token(client_id=CLIENT_ID, nonce=nonce, email=EMAIL, keys=keys, issuer=fake_oidc_idp.ISSUER),
    "ACCEPTED",
)

# B: wrong nonce (attacker captured a code from their own flow, replays against a victim's state/nonce)
case(
    "B_wrong_nonce",
    lambda nonce: make_id_token(client_id=CLIENT_ID, nonce="not-the-real-nonce", email=EMAIL, keys=keys, issuer=fake_oidc_idp.ISSUER),
    "REFUSED",
)

# C: wrong audience (aud != client_id)
case(
    "C_wrong_audience",
    lambda nonce: make_id_token(client_id=CLIENT_ID, nonce=nonce, email=EMAIL, keys=keys, audience="some-other-client", issuer=fake_oidc_idp.ISSUER),
    "REFUSED",
)

# D: expired id_token
case(
    "D_expired",
    lambda nonce: make_id_token(client_id=CLIENT_ID, nonce=nonce, email=EMAIL, keys=keys, expires_in=-3600, issuer=fake_oidc_idp.ISSUER),
    "REFUSED",
)

# E: wrong issuer
case(
    "E_wrong_issuer",
    lambda nonce: make_id_token(client_id=CLIENT_ID, nonce=nonce, email=EMAIL, keys=keys, issuer="http://not-the-real-idp.test"),
    "REFUSED",
)

# F: foreign-signed (attacker's own key, not the registered IdP's -- so the kid won't even
# match any key in our JWKS; still try it to see the failure mode)
case(
    "F_foreign_signed_key",
    lambda nonce: make_id_token(client_id=CLIENT_ID, nonce=nonce, email=EMAIL, keys=attacker_keys(), issuer=fake_oidc_idp.ISSUER),
    "REFUSED",
)

# G: email_verified explicitly false (even with trust_unverified_email ON for this org)
case(
    "G_email_verified_false",
    lambda nonce: make_id_token(client_id=CLIENT_ID, nonce=nonce, email=EMAIL, keys=keys, email_verified=False, issuer=fake_oidc_idp.ISSUER),
    "REFUSED",
)

# H: alg confusion -- HS256, "signed" using the RSA public key's PEM text as the HMAC secret
# (the classic RS256->HS256 downgrade attack: if the verifier ever treated a public key as a
# valid HMAC secret, this would forge a token for ANY identity without the real private key)
import jwt as pyjwt

def h_token(nonce):
    import base64, hmac, hashlib
    from cryptography.hazmat.primitives import serialization
    now = int(time.time())
    claims = {
        "iss": fake_oidc_idp.ISSUER, "aud": CLIENT_ID, "sub": "attacker",
        "iat": now, "exp": now + 300, "nonce": nonce,
        "email": "bb-owner@dumbpotato.com", "email_verified": True, "name": "Attacker",
    }
    pubkey_pem = keys.cert.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    def b64u(b):
        return base64.urlsafe_b64encode(b).rstrip(b"=")
    header = b64u(json.dumps({"alg": "HS256", "typ": "JWT", "kid": OIDC_KID}).encode())
    payload = b64u(json.dumps(claims).encode())
    signing_input = header + b"." + payload
    sig = b64u(hmac.new(pubkey_pem, signing_input, hashlib.sha256).digest())
    return (signing_input + b"." + sig).decode()

case("H_alg_confusion_HS256_with_public_key", h_token, "REFUSED")

# I: alg=none
def none_token(nonce):
    now = int(time.time())
    claims = {
        "iss": fake_oidc_idp.ISSUER, "aud": CLIENT_ID, "sub": "attacker",
        "iat": now, "exp": now + 300, "nonce": nonce,
        "email": "bb-owner@dumbpotato.com", "email_verified": True, "name": "Attacker",
    }
    header = __import__("base64").urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    payload = __import__("base64").urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}."

case("I_alg_none", none_token, "REFUSED")

# J: replay -- use the SAME (state, code) pair twice
state_j, nonce_j, cj_j = start_login()
code_j = f"code-replay-{int(time.time()*1000)}"
fake_oidc_idp.CODES[code_j] = make_id_token(client_id=CLIENT_ID, nonce=nonce_j, email="bb-sso2@dumbpotato.com", keys=keys, issuer=fake_oidc_idp.ISSUER)
st1, loc1 = callback(state_j, code_j, cj_j)
st2, loc2 = callback(state_j, code_j, cj_j)
RESULTS.append({"case": "J_replay_same_state_and_code", "first": {"status": st1, "outcome": classify(loc1)},
                 "second": {"status": st2, "outcome": classify(loc2), "location": loc2[:160]}, "expect": "second=REFUSED"})

print(json.dumps(RESULTS, indent=2, default=str))
with open("/mnt/files/projects/builder-backend/final_test/security/evidence/oidc_full_flow_results.json", "w") as f:
    json.dump(RESULTS, f, indent=2, default=str)
