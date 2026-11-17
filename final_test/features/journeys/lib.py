"""Shared helpers for the feature journeys. Everything is redacted; results go to features/logs/results.jsonl"""
import json, os, re, sys, time, uuid, pathlib
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "harness"))
os.environ["MAIL"] = os.environ.get("BBF_MAIL", "sink")
import bb  # noqa: E402

LOG = HERE.parent / "logs" / "results.jsonl"
A = bb.Api()
PW = A.password()
RUN = uuid.uuid4().hex[:6]
_SECRET = re.compile(r"(eyJ[\w-]{10,}\.[\w-]+\.[\w-]+|bbk_[\w-]+|sk_(test|live)_\w+|whsec_\w+)")

def redact(s):
    return _SECRET.sub("[REDACTED]", str(s))

def rec(jid, desc, ok, detail=""):
    row = {"id": jid, "desc": desc, "ok": bool(ok), "detail": redact(detail)[:600], "ts": int(time.time())}
    with LOG.open("a") as f:
        f.write(json.dumps(row) + "\n")
    print(("PASS " if ok else "FAIL ") + jid, desc, "" if ok else "-> " + row["detail"], flush=True)
    return ok

def expect(jid, desc, resp, status, extra=None):
    c, b, h = resp
    ok = (c in status) if isinstance(status, (list, tuple, set)) else c == status
    if ok and extra:
        ok = extra(b)
    return rec(jid, desc, ok, f"HTTP {c} {json.dumps(b)[:400]}")

def signup(email, name="t", pw=None):
    c, b, h = A.call("POST", "/account/register", {"email": email, "password": pw or PW, "name": name})
    return c, b, h

def user(tag):
    """fresh account -> (email, token)"""
    em = f"bbf-{tag}-{RUN}@" + os.environ.get("BBF_DOMAIN", "dumbpotato.com")
    c, b, _ = signup(em)
    assert c == 201, (c, b)
    return em, b["access_token"]

def call(tok, m, p, body=None, headers=None):
    return A.call(m, p, body, tok, headers)
