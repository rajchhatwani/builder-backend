"""Keeps secrets out of logs and audit records (generated).

Two layers: values stored under a secret-sounding key are replaced wholesale, and any string is
scanned for the shapes secrets have (API keys, signing secrets, bearer tokens, JWTs, signature
headers, passwords inside URLs). It is a safety net, not a licence to log secrets.
"""

import re
from typing import Any

REDACTED = "[redacted]"

_SECRET_KEY_RE = re.compile(
    r"(pass(word|wd)?|secret|token|authorization|signature|api[-_]?key|cookie|credential|"
    r"private[-_]?key|client[-_]?secret)",
    re.IGNORECASE,
)
_VALUE_PATTERNS = (
    re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{8,}"),
    re.compile(r"\bwhsec_[A-Za-z0-9+/=_-]{8,}"),
    re.compile(r"\brzp_(?:live|test)_[A-Za-z0-9]{6,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"),
    re.compile(r"\bt=\d{6,},v1=[0-9a-fA-F]{16,}[0-9a-fA-F,=v]*"),
    re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)"),
)
_MAX_DEPTH = 8
# Secrets known by value (a provider whose secrets look like any other string). Registered by the
# code that loads them; the shapes above cannot catch these.
_LITERALS: set[str] = set()
_MIN_LITERAL = 8


def register_secret(value: str) -> None:
    """From now on `value` is hidden wherever it appears in a log line or an audit record."""
    if len(value) >= _MIN_LITERAL:
        _LITERALS.add(value)


def scrub_text(text: str) -> str:
    for secret in _LITERALS:
        text = text.replace(secret, REDACTED)
    for pattern in _VALUE_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def scrub(value: Any, _depth: int = 0) -> Any:
    """A copy of `value` (dicts, lists, strings) with secrets replaced."""
    if _depth > _MAX_DEPTH:
        return REDACTED
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        return {
            k: REDACTED if _SECRET_KEY_RE.search(str(k)) else scrub(v, _depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [scrub(v, _depth + 1) for v in value]
    return value


def redact_processor(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """structlog processor: scrub every field of a log record."""
    return {k: scrub(v) if k != "event" else scrub_text(str(v)) for k, v in event_dict.items()}
