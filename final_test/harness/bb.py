#!/usr/bin/env python3
"""Shared helpers for the final-test sessions. Standard library only. Import it or use the CLI.

    import sys; sys.path.insert(0, "final_test/harness"); import bb
    api = bb.Api()                          # http://127.0.0.1:8000 by default (BB_API env overrides)
    tok = api.customer("owner")             # roles: individual owner admin member outsider  (signs up first if needed)
    tok = api.staff("admin")                # roles: admin support (password + generated TOTP)
    status, body, headers = api.call("GET", "/orgs/bb-sso", token=tok)
    msg = bb.wait_mail(to="bb_member@dumbpotato.com", subject="invited", timeout=120)   # real inbox via IMAP
    msg["links"]                            # URLs found in the mail (an invite link carries a live token!)

CLI:   python3 final_test/harness/bb.py roles | totp admin|support | mail --to X --subject Y [--wait 90]

RULES: never print or store a token, password, TOTP secret, recovery code or invite link in any report or log.
The CLI redacts links; the functions return the raw values for your scripts only.
"""

from __future__ import annotations

import argparse
import base64
import email as email_lib
import hashlib
import hmac
import imaplib
import json
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.request
from email.header import decode_header, make_header
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "credentials"))
from check_env import load_env  # noqa: E402

ENV_FILE = Path(os.environ.get("ENV_FILE", Path.home() / "final_test.env")).expanduser()


def env() -> dict[str, str]:
    return load_env(ENV_FILE)


def totp(secret: str, at: float | None = None) -> str:
    s = secret.replace(" ", "").upper()
    key = base64.b32decode(s + "=" * (-len(s) % 8))
    mac = hmac.new(key, struct.pack(">Q", int(at or time.time()) // 30), hashlib.sha1).digest()
    o = mac[-1] & 15
    return str((struct.unpack(">I", mac[o : o + 4])[0] & 0x7FFFFFFF) % 10**6).zfill(6)


# role -> (email env var, password source). Customer passwords are all FINAL_TEST_PASSWORD.
ROLES = {
    "individual": "FINAL_TEST_INDIVIDUAL_EMAIL",
    "owner": "FINAL_TEST_OWNER_EMAIL",
    "admin": "FINAL_TEST_ADMIN_EMAIL",
    "member": "FINAL_TEST_MEMBER_EMAIL",
    "outsider": "FINAL_TEST_OUTSIDER_EMAIL",
}


class Api:
    def __init__(self, base: str | None = None):
        self.base = (base or os.environ.get("BB_API") or "http://127.0.0.1:8000").rstrip("/")
        self.e = env()

    def call(self, method: str, path: str, body=None, token: str | None = None, headers: dict | None = None):
        h = {"Content-Type": "application/json", **(headers or {})}
        if token:
            h["Authorization"] = "Bearer " + token
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data, h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else {}), dict(r.headers)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw) if raw else {}, dict(exc.headers)
            except ValueError:
                return exc.code, {}, dict(exc.headers)

    # -- customers ---------------------------------------------------------------------------
    def email_of(self, role: str) -> str:
        return self.e[ROLES[role]]

    def password(self) -> str:
        return self.e["FINAL_TEST_PASSWORD"]

    def login(self, email: str, password: str, totp_secret: str | None = None, audience: str = "account") -> str | None:
        c, b, _ = self.call("POST", f"/{audience}/login", {"email": email, "password": password})
        if c == 200 and "mfa_token" in b:
            if b.get("enrollment_required") or not totp_secret:
                return None
            tok = b["mfa_token"]
            c, b, _ = self.call("POST", f"/{audience}/login/mfa", {"mfa_token": tok, "code": totp(totp_secret)})
            if c == 401:  # the app refuses a TOTP code twice in one 30 s step (replay protection): wait for the next step
                time.sleep(30 - time.time() % 30 + 1)
                c, b, _ = self.call("POST", f"/{audience}/login/mfa", {"mfa_token": tok, "code": totp(totp_secret)})
        return b.get("access_token") if c == 200 else None

    def customer(self, role: str, sign_up: bool = True) -> str:
        """Access token for a customer test account; signs it up on first use (the DB snapshot has only bb-owner)."""
        em, pw = self.email_of(role), self.password()
        tok = self.login(em, pw)
        if tok:
            return tok
        if sign_up:
            c, b, _ = self.call("POST", "/account/register", {"email": em, "password": pw, "name": role})
            if c == 201:
                return b["access_token"]
        raise RuntimeError(f"cannot sign in or sign up customer role '{role}' (HTTP {c if sign_up else 'n/a'})")

    # -- platform staff ----------------------------------------------------------------------
    def staff(self, role: str = "admin") -> str:
        if role == "admin":
            em, pw, sec = self.e["FINAL_TEST_PLATFORM_ADMIN_EMAIL"], self.e["BUILDER_BOOTSTRAP_ADMIN_PASSWORD"], self.e["FINAL_TEST_PLATFORM_ADMIN_TOTP_SECRET"]
        else:
            em, pw, sec = self.e["FINAL_TEST_PLATFORM_SUPPORT_EMAIL"], self.password(), self.e["FINAL_TEST_PLATFORM_SUPPORT_TOTP_SECRET"]
        tok = self.login(em, pw, sec, audience="admin")
        if not tok:
            raise RuntimeError(f"staff sign-in failed for '{role}' (TOTP secret current? run credentials/verify_totp.py)")
        return tok


# -- the real inbox (GoDaddy IMAP, the mailbox that the bb_* aliases deliver to) ----------------


def _decode(v) -> str:
    return str(make_header(decode_header(v or "")))


def _body(msg) -> str:
    parts = []
    for p in msg.walk():
        if p.get_content_type() in ("text/plain", "text/html"):
            payload = p.get_payload(decode=True) or b""
            parts.append(payload.decode(p.get_content_charset() or "utf-8", "replace"))
    return "\n".join(parts)


def wait_mail(to: str | None = None, subject: str | None = None, timeout: int = 90, since: float | None = None, scan: int = 40):
    """Poll the inbox until a mail whose To/Cc contains `to` and Subject contains `subject` arrived after `since`
    (epoch seconds; default: 5 minutes ago). Returns {subject,to,date,body,links} or None on timeout."""
    e = env()
    since = since if since is not None else time.time() - 300
    deadline = time.time() + timeout
    if os.environ.get("MAIL") == "sink":  # stack.sh up ... with MAIL=sink: read the local Mailpit instead of IMAP
        return _wait_sink(to, subject, deadline, since)
    while True:
        m = imaplib.IMAP4_SSL(e.get("FINAL_TEST_IMAP_HOST", "imap.secureserver.net"), 993, timeout=20)
        try:
            m.login(e["BUILDER_SMTP_USERNAME"], e["BUILDER_SMTP_PASSWORD"])
            for folder in ("INBOX", "Spam", "Junk"):
                if m.select(folder, readonly=True)[0] != "OK":
                    continue
                ids = m.search(None, "ALL")[1][0].split()[-scan:]
                for i in reversed(ids):
                    # INTERNALDATE (server receive time): the app's mails carry no Date header
                    resp = m.fetch(i, "(INTERNALDATE BODY.PEEK[])")[1]
                    meta = resp[0][0].decode()
                    tup = imaplib.Internaldate2tuple(meta.encode())
                    ts = time.mktime(tup) if tup else 0
                    msg = email_lib.message_from_bytes(resp[0][1])
                    hay_to = (_decode(msg["To"]) + " " + _decode(msg["Cc"])).lower()
                    subj = _decode(msg["Subject"])
                    if ts >= since - 60 and (not to or to.lower() in hay_to) and (not subject or subject.lower() in subj.lower()):
                        body = _body(msg)
                        return {"subject": subj, "to": hay_to.strip(), "date": ts, "folder": folder, "body": body,
                                "links": re.findall(r"https?://[^\s<>\"')]+", body)}
        finally:
            try:
                m.logout()
            except Exception:  # noqa: BLE001
                pass
        if time.time() >= deadline:
            return None
        time.sleep(5)


def _wait_sink(to, subject, deadline, since):
    base = os.environ.get("BB_MAILPIT", "http://127.0.0.1:8025")
    while True:
        with urllib.request.urlopen(base + "/api/v1/messages?limit=50", timeout=10) as r:
            for m in json.loads(r.read()).get("messages", []):
                tos = " ".join(x["Address"] for x in m.get("To", [])).lower()
                if (not to or to.lower() in tos) and (not subject or subject.lower() in m["Subject"].lower()):
                    with urllib.request.urlopen(f"{base}/api/v1/message/{m['ID']}", timeout=10) as r2:
                        body = json.loads(r2.read()).get("Text", "")
                    return {"subject": m["Subject"], "to": tos, "date": time.time(), "folder": "mailpit", "body": body,
                            "links": re.findall(r"https?://[^\s<>\"')]+", body)}
        if time.time() >= deadline:
            return None
        time.sleep(2)


def inbox_folders() -> list[str]:
    e = env()
    m = imaplib.IMAP4_SSL("imap.secureserver.net", 993, timeout=20)
    m.login(e["BUILDER_SMTP_USERNAME"], e["BUILDER_SMTP_PASSWORD"])
    out = [x.decode() for x in m.list()[1]]
    m.logout()
    return out


# -- act as an IdP's SCIM client (no Okta needed): Authorization: Bearer <bb_scim_ token> -------


class Scim:
    def __init__(self, base: str, token: str):
        self.base, self.token = base.rstrip("/"), token

    def call(self, method: str, path: str, body=None):
        h = {"Content-Type": "application/scim+json", "Authorization": "Bearer " + self.token}
        req = urllib.request.Request(self.base + path, json.dumps(body).encode() if body is not None else None, h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return r.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw) if raw else {}
            except ValueError:
                return exc.code, {}


def stripe_webhook(event_type: str, obj: dict, api: str | None = None, secret: str | None = None,
                   timestamp: int | None = None, event_id: str | None = None, livemode: bool = False):
    """POST a correctly SIGNED Stripe event (HMAC with BUILDER_STRIPE_WEBHOOK_SECRET, the first secret in the list)
    to the app's webhook, like Stripe does. Tamper with the arguments to test forgery/replay/out-of-order cases.
    Returns (status, body)."""
    e = env()
    secret = secret or e["BUILDER_STRIPE_WEBHOOK_SECRET"].split(",")[0].strip()
    ts = int(timestamp if timestamp is not None else time.time())
    payload = json.dumps({"id": event_id or f"evt_ft_{ts}_{os.urandom(3).hex()}", "object": "event", "type": event_type,
                          "livemode": livemode, "created": ts, "data": {"object": obj}}, separators=(",", ":"))
    sig = hmac.new(secret.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
    base = (api or os.environ.get("BB_API") or "http://127.0.0.1:8000").rstrip("/")
    req = urllib.request.Request(base + "/billing/stripe/webhook", payload.encode(),
                                 {"Content-Type": "application/json", "Stripe-Signature": f"t={ts},v1={sig}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()[:200]
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()[:200]


def _redact(url: str) -> str:
    return re.sub(r"(/invite/|token=)[^&/#\s]+", r"\1[REDACTED]", url)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("roles")
    t = sub.add_parser("totp"); t.add_argument("who", choices=["admin", "support"])
    m = sub.add_parser("mail"); m.add_argument("--to"); m.add_argument("--subject"); m.add_argument("--wait", type=int, default=0)
    a = ap.parse_args()
    e = env()
    if a.cmd == "roles":
        for r, k in ROLES.items():
            print(f"{r:<11} {e.get(k)}")
        print(f"{'admin':<11} {e.get('FINAL_TEST_PLATFORM_ADMIN_EMAIL')}  (staff, TOTP)")
        print(f"{'support':<11} {e.get('FINAL_TEST_PLATFORM_SUPPORT_EMAIL')}  (staff, TOTP)")
    elif a.cmd == "totp":
        print(totp(e[f"FINAL_TEST_PLATFORM_{a.who.upper()}_TOTP_SECRET"]))
    else:
        msg = wait_mail(a.to, a.subject, a.wait or 1)
        if not msg:
            print("no matching mail"); return 1
        print(json.dumps({"subject": msg["subject"], "to": msg["to"], "links": [_redact(x) for x in msg["links"]]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
