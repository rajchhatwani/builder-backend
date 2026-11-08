"""Checkpoint: SQLi/XSS/SSTI/path-traversal/header-injection marker payloads in org names, live."""
import sys, json
sys.path.insert(0, "final_test/harness")
import bb
api = bb.Api()
tok = api.customer("owner")
payloads = [
    "Evil\r\nBcc: attacker@evil.test\r\nSubject: pwned",
    "<script>alert(1)</script>",
    "{{7*7}}",
    "../../../etc/passwd",
    "'; DROP TABLE organizations; --",
]
for i, p in enumerate(payloads):
    st, b, _ = api.call("POST", "/orgs", {"name": p, "slug": f"inj-test-{i}"}, token=tok)
    print(f"org name={p!r} -> {st} {str(b)[:200]}")
# Structural checks (code, not live): no `dangerouslySetInnerHTML` in frontend/src; mail is
# plain-text only (mail_service.py); SQL via SQLAlchemy ORM throughout, no raw text(f"...");
# code generator uses jinja2.sandbox.SandboxedEnvironment + FileSystemLoader (fixed template
# files, never a dynamically-built template string) -- see SECURITY_REPORT.md for detail.
