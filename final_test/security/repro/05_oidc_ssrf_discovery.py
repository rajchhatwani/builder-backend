"""Checkpoint 2: SSRF guard on the OIDC discovery_url, tested against the live stack.
Run against the live stack (final_test/harness/stack.sh up production) as the org owner."""
import sys, json
sys.path.insert(0, "final_test/harness")
import bb

api = bb.Api()
tok = api.customer("owner")

TARGETS = [
    "http://127.0.0.1:8000/.well-known/openid-configuration",
    "https://127.0.0.1:8000/.well-known/openid-configuration",
    "http://169.254.169.254/latest/meta-data/",
    "https://metadata.google.internal/computeMetadata/v1/",
]

for url in TARGETS:
    cfg = {
        "protocol": "oidc", "oidc_discovery_url": url, "oidc_client_id": "test-client",
        "oidc_client_secret": "test-secret", "jit_enabled": True, "jit_role": "member",
        "trust_unverified_email": True,
    }
    st_put, b_put, _ = api.call("PUT", "/orgs/bb-sso/sso", cfg, token=tok)
    st_chk, b_chk, _ = api.call("POST", "/orgs/bb-sso/sso/check", {}, token=tok)
    print(url, "-> PUT", st_put, b_put.get("code"), "| check", st_chk, json.dumps(b_chk)[:200])

# NOTE: this test mutates the org's SSO config; restore the `configured` snapshot afterward:
#   final_test/harness/stack.sh restore configured
