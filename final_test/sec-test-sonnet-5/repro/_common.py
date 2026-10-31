"""Shared helpers for this session's repro scripts. Import, don't run directly.

Redaction rule: never print/log a raw token, password, TOTP secret, recovery code or cookie.
Use `redact()` on anything that might contain one before printing or writing to evidence/.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "final_test" / "harness"))
import bb  # noqa: E402

SESSION_DIR = ROOT / "final_test" / "sec-test-sonnet-5"
EVIDENCE_DIR = SESSION_DIR / "evidence"
LOG_DIR = SESSION_DIR / "logs"
FINDINGS_PATH = SESSION_DIR / "findings.jsonl"

_REDACT_PATTERNS = [
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT-ish
    re.compile(r"bb_scim_[A-Za-z0-9]+"),
    re.compile(r"bb_token_[A-Za-z0-9_]+"),
]


def redact(value):
    if value is None:
        return value
    s = value if isinstance(value, str) else json.dumps(value, default=str)
    for pat in _REDACT_PATTERNS:
        s = pat.sub("[REDACTED]", s)
    return s


def tunnel_api_base() -> str:
    e = bb.env()
    return e["FINAL_TEST_TUNNEL_API_URL"].rstrip("/")


def local_api_base() -> str:
    return os.environ.get("BB_LOCAL_API", "http://127.0.0.1:8001")


def new_disposable_email(prefix: str) -> str:
    """An address on a domain we don't need real mail for; sign-up never verifies e-mail (F-005)."""
    return f"sectest-{prefix}-{uuid.uuid4().hex[:8]}@sectest.example"


def record(category: str, item_id: str, title: str, expected: str, actual: str,
           severity: str, status: str, note: str = "", repro: str = ""):
    """Append one finding/observation line to findings.jsonl (append-only running log)."""
    FINDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": time.time(),
        "category": category,
        "id": item_id,
        "title": title,
        "expected": expected,
        "actual": redact(actual),
        "severity": severity,  # Critical/High/Medium/Low/Info
        "status": status,      # CONFIRMED/SUSPECTED/SOLID (passed)/NOT_TESTABLE
        "note": redact(note),
        "repro": repro,
    }
    with FINDINGS_PATH.open("a") as f:
        f.write(json.dumps(row) + "\n")
    print(f"[{severity:>8}] {status:<12} {category}/{item_id}: {title}")
    return row


def ngrok_headers(extra: dict | None = None) -> dict:
    h = {"ngrok-skip-browser-warning": "1"}
    if extra:
        h.update(extra)
    return h
