"""Checkpoint 6: TOTP replay + recovery-code single-use, live."""
import sys, json
sys.path.insert(0, "final_test/harness")
import bb

api = bb.Api()
e = bb.env()
em, pw, sec = e["FINAL_TEST_PLATFORM_ADMIN_EMAIL"], e["BUILDER_BOOTSTRAP_ADMIN_PASSWORD"], e["FINAL_TEST_PLATFORM_ADMIN_TOTP_SECRET"]

st, b, _ = api.call("POST", "/admin/login", {"email": em, "password": pw})
mfa_token = b["mfa_token"]
code = bb.totp(sec)
st1, b1, _ = api.call("POST", "/admin/login/mfa", {"mfa_token": mfa_token, "code": code})
print("TOTP first use:", st1)
st2, b2, _ = api.call("POST", "/admin/login/mfa", {"mfa_token": mfa_token, "code": code})
print("TOTP replay (same code, same mfa_token):", st2, b2)

# Recovery-code reuse: see final_test/security/evidence/recovery_code_reuse_result.json for the
# full enroll -> use -> reuse sequence against a disposable customer account.
